from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
import time
import warnings
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Type, cast

import httpx
from typing_extensions import Self, override
from yandex.cloud.iam.v1.iam_token_service_pb2 import (  # pylint: disable=no-name-in-module
    CreateIamTokenRequest, CreateIamTokenResponse
)
from yandex.cloud.iam.v1.iam_token_service_pb2_grpc import IamTokenServiceStub

if TYPE_CHECKING:
    from ._client import AsyncCloudClient


class BaseAuth(ABC):
    @abstractmethod
    async def get_auth_metadata(self, client: AsyncCloudClient, timeout: float) -> tuple[str, str] | None:
        pass

    @classmethod
    @abstractmethod
    async def applicable_from_env(cls, **kwargs) -> Self | None:
        pass


class NoAuth(BaseAuth):
    @override
    async def get_auth_metadata(self, client: AsyncCloudClient, timeout: float) -> None:
        return None

    @override
    @classmethod
    async def applicable_from_env(cls, **kwargs) -> None:
        return None


class APIKeyAuth(BaseAuth):
    env_var = 'YC_API_KEY'

    def __init__(self, api_key):
        self._api_key = api_key

    @override
    async def get_auth_metadata(self, client: AsyncCloudClient, timeout: float) -> tuple[str, str]:
        return ('authorization', f'Api-Key {self._api_key}')

    @override
    @classmethod
    async def applicable_from_env(cls, **kwargs) -> Self | None:
        api_key = os.getenv(cls.env_var)
        if api_key:
            return cls(api_key)

        return None


class BaseIAMTokenAuth(BaseAuth):
    def __init__(self, token: str | None):
        self._token = token

    @override
    async def get_auth_metadata(self, client: AsyncCloudClient, timeout: float) -> tuple[str, str]:
        return ('authorization', f'Bearer {self._token}')


class IAMTokenAuth(BaseIAMTokenAuth):
    env_var = 'YC_IAM_TOKEN'

    def __init__(self, token: str):
        super().__init__(token)

    @override
    @classmethod
    async def applicable_from_env(cls, **kwargs) -> Self | None:
        token = os.getenv(cls.env_var)
        if token:
            return cls(token)

        return None


class RefresheableIAMTokenAuth(BaseIAMTokenAuth):
    _token_refresh_period = 60 * 60

    def __init__(self, token) -> None:
        super().__init__(token)
        self._issue_time: float | None = None
        if self._token is not None:
            self._issue_time = time.time()

    @override
    async def get_auth_metadata(self, client: AsyncCloudClient, timeout: float) -> tuple[str, str]:
        if (
            self._token is None or
            self._issue_time is None or
            time.time() - self._issue_time > self._token_refresh_period
        ):
            self._token = await self._get_token(client, timeout=timeout)
            self._issue_time = time.time()

        return await super().get_auth_metadata(client, timeout=timeout)

    @abstractmethod
    async def _get_token(self, client: AsyncCloudClient, timeout: float) -> str:
        pass


class OAuthTokenAuth(RefresheableIAMTokenAuth):
    env_var = 'YC_OAUTH_TOKEN'

    def __init__(self, token):
        self._oauth_token = token
        super().__init__(None)

    @override
    @classmethod
    async def applicable_from_env(cls, **kwargs) -> Self | None:
        token = os.getenv(cls.env_var)
        if token:
            return cls(token)

        return None

    @override
    async def _get_token(self, client: AsyncCloudClient, timeout: float) -> str:
        request = CreateIamTokenRequest(yandex_passport_oauth_token=self._oauth_token)
        async with client.get_service_stub(IamTokenServiceStub, timeout=timeout) as stub:
            result = await client.call_service(
                stub.Create,
                request=request,
                timeout=timeout,
                expected_type=CreateIamTokenResponse,
                auth=False,
            )
        return result.iam_token


class YandexCloudCLIAuth(RefresheableIAMTokenAuth):
    env_var = 'YC_PROFILE'

    def __init__(self, token: str | None = None, endpoint: str | None = None, yc_profile: str | None = None):
        super().__init__(token)
        self._endpoint = endpoint
        self._yc_profile = yc_profile

    @classmethod
    def _build_command(cls, yc_profile: str | None, endpoint: str | None) -> list[str]:
        cmd = ['yc', 'iam', 'create-token', '--no-user-output']
        if endpoint:
            cmd.extend(['--endpoint', endpoint])

        if yc_profile:
            cmd.extend(['--profile', yc_profile])

        return cmd

    @classmethod
    async def _check_output(cls, command: list[str]) -> str | None:
        process = await asyncio.create_subprocess_exec(
            *command,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL
        )
        stdout, _ = await process.communicate()
        if process.returncode:
            return None

        result = stdout.splitlines(keepends=False)
        return result[-1].decode('utf-8')

    @classmethod
    async def applicable_from_env(cls, **kwargs) -> Self | None:
        yc_profile: str | None = kwargs.get('yc_profile') or os.getenv(cls.env_var)
        endpoint: str | None = kwargs.get('endpoint')

        if not sys.stdin.isatty():
            return None

        if not shutil.which('yc'):
            return None

        if endpoint:
            endpoint_cmd = ['yc', 'config', 'get', 'endpoint']
            if yc_profile:
                endpoint_cmd.extend(['--profile', yc_profile])

            yc_endpoint = await cls._check_output(endpoint_cmd)
            if yc_endpoint != endpoint:
                return None

        cmd = cls._build_command(yc_profile, endpoint)
        token = await cls._check_output(cmd)
        if token is None:
            return None

        return cls(
            token,
            endpoint=endpoint,
            yc_profile=yc_profile
        )

    @override
    async def _get_token(self, client: AsyncCloudClient, timeout: float) -> str:
        cmd = self._build_command(self._yc_profile, self._endpoint)
        if not (token := await self._check_output(cmd)):
            raise RuntimeError('failed to fetch iam token from yc cli')

        return token


class MetadataAuth(RefresheableIAMTokenAuth):
    env_var = 'YC_METADATA_ADDR'
    _headers = {'Metadata-Flavor': 'Google'}
    _default_addr = '169.254.169.254'

    def __init__(self, token: str | None = None, metadata_url: str | None = None):
        self._metadata_url: str = metadata_url or self._default_addr
        super().__init__(token)

    @override
    @classmethod
    async def applicable_from_env(cls, **kwargs) -> Self | None:
        addr = os.getenv(cls.env_var, cls._default_addr)
        url = f'http://{addr}/computeMetadata/v1/instance/service-accounts/default/token'
        # In case we found env var, we 99% would use this Auth, so timeout became
        # irrelevant
        timeout = 1 if cls.env_var in os.environ else 0.1

        try:
            token = await cls._request_token(timeout, url)
        except (httpx.NetworkError, httpx.HTTPError, json.JSONDecodeError):
            return None

        return cls(token, url)

    @override
    async def _get_token(self, client: AsyncCloudClient | None, timeout: float) -> str:
        return await self._request_token(timeout, self._metadata_url)

    @classmethod
    async def _request_token(cls, timeout: float, metadata_url: str) -> str:
        async with httpx.AsyncClient() as client:
            response = await client.get(
                metadata_url,
                headers=cls._headers,
                timeout=timeout,
            )
            response.raise_for_status()

        data = response.json()
        return data['access_token']


async def get_auth_provider(
    *,
    auth: str | BaseAuth | None,
    endpoint: str,
    yc_profile: str | None,
) -> BaseAuth:
    simple_iam_regexp = re.compile(r'^t\d\.')
    iam_regexp = re.compile(r't1\.[A-Z0-9a-z_-]+[=]{0,2}\.[A-Z0-9a-z_-]{86}[=]{0,2}')

    result: BaseAuth | None = None
    if isinstance(auth, str):
        if simple_iam_regexp.match(auth):
            result = IAMTokenAuth(auth)
            if not iam_regexp.match(auth):
                warnings.warn(
                    "auth argument was classified as IAM token but it doesn't match IAM token format; "
                    "in case of any troubles you could create Auth object directly.",
                    UserWarning,
                    stacklevel=2,
                )
        else:
            result = APIKeyAuth(auth)
    elif isinstance(auth, BaseAuth):
        result = auth
    elif auth is not None:
        raise RuntimeError(
            'auth argument must be a string (in case of APIKey), instance of BaseAuth or Undefined'
        )
    else:
        for cls in (
            APIKeyAuth,
            IAMTokenAuth,
            OAuthTokenAuth,
            MetadataAuth,
            YandexCloudCLIAuth,
        ):
            cls = cast(Type[BaseAuth], cls)
            result = await cls.applicable_from_env(
                yc_profile=yc_profile,
                endpoint=endpoint,
            )
            if result:
                break

    if not result:
        raise RuntimeError(
            'no explicit authorization data was passed and no authorization data was found at environment',
        )

    return result