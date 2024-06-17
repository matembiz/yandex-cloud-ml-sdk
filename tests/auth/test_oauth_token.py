# pylint: disable=protected-access
from __future__ import annotations

import time

import pytest
from yandex.cloud.iam.v1.iam_token_service_pb2 import CreateIamTokenResponse  # pylint: disable=no-name-in-module
from yandex.cloud.iam.v1.iam_token_service_pb2_grpc import (
    IamTokenServiceServicer, add_IamTokenServiceServicer_to_server
)

from yandex_cloud_ml_sdk.auth import OAuthTokenAuth

pytestmark = pytest.mark.asyncio


@pytest.fixture(name="oauth_token")
def fixture_oauth_token():
    return "<oauth_token>"


@pytest.fixture(name="auth")
def fixture_auth(oauth_token):
    return OAuthTokenAuth(oauth_token)


@pytest.fixture
def servicers(oauth_token):
    class Servicer(IamTokenServiceServicer):
        def __init__(self):
            self.i = 0

        def Create(self, request, context):
            assert request.yandex_passport_oauth_token == oauth_token

            response = CreateIamTokenResponse(iam_token=f"<iam-token-{self.i}>")
            self.i += 1
            return response

    return [(Servicer(), add_IamTokenServiceServicer_to_server)]


async def test_auth(async_sdk, test_client, auth):
    async_sdk._client = test_client

    metadata = await async_sdk._client._get_metadata(auth_required=True, timeout=1)

    assert auth._issue_time is not None
    assert metadata == (("authorization", "Bearer <iam-token-0>"),)


async def test_reissue(async_sdk, test_client, auth, monkeypatch):
    async_sdk._client = test_client

    assert auth._token is None
    assert auth._issue_time is None

    await async_sdk._client._get_metadata(auth_required=True, timeout=1)
    assert auth._token == "<iam-token-0>"
    assert auth._issue_time is not None

    issue_time = auth._issue_time
    time.sleep(1)

    # no reissue after second request
    await async_sdk._client._get_metadata(auth_required=True, timeout=1)
    assert auth._issue_time == issue_time
    assert auth._token == "<iam-token-0>"

    # now we will trigger reissue of a token
    monkeypatch.setattr(auth, "_token_refresh_period", 1)

    await async_sdk._client._get_metadata(auth_required=True, timeout=1)
    assert auth._token == "<iam-token-1>"
    assert auth._issue_time > issue_time


async def test_applicable_from_env(oauth_token, monkeypatch):
    monkeypatch.delenv(OAuthTokenAuth.env_var, raising=False)
    assert await OAuthTokenAuth.applicable_from_env() is None

    monkeypatch.setenv(OAuthTokenAuth.env_var, oauth_token)
    auth = await OAuthTokenAuth.applicable_from_env()
    assert auth
    assert auth._oauth_token == oauth_token
