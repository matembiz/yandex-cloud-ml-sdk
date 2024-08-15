from __future__ import annotations

import asyncio
import time

import pytest
# pylint: disable-next=no-name-in-module
from yandex.cloud.ai.foundation_models.v1.text_generation.text_generation_service_pb2 import CompletionResponse
from yandex.cloud.ai.foundation_models.v1.text_generation.text_generation_service_pb2_grpc import (
    TextGenerationServiceServicer, add_TextGenerationServiceServicer_to_server
)
# pylint: disable-next=no-name-in-module
from yandex.cloud.endpoint.api_endpoint_service_pb2 import ListApiEndpointsRequest, ListApiEndpointsResponse
from yandex.cloud.endpoint.api_endpoint_service_pb2_grpc import ApiEndpointServiceStub

from yandex_cloud_ml_sdk import AsyncYCloudML


@pytest.fixture(name='servicers')
def fixture_servicers():
    class TextGenerationServicer(TextGenerationServiceServicer):
        def __init__(self):
            self.i = 0

        def Completion(self, request, context):
            for i in range(10):
                yield CompletionResponse(
                    alternatives=[],
                    usage=None,
                    model_version=str(i)
                )

                self.i += 1

                time.sleep(1)

    return [
        (TextGenerationServicer(), add_TextGenerationServiceServicer_to_server),
    ]


@pytest.mark.heavy
@pytest.mark.asyncio
async def test_multiple_requests(folder_id):
    async_sdk = AsyncYCloudML(folder_id=folder_id)
    test_client = async_sdk._client

    stubs = []
    ctx = []
    for _ in range(20000):
        context = test_client.get_service_stub(ApiEndpointServiceStub, 10)
        ctx.append(context)
        stub = await context.__aenter__()  # pylint: disable=no-member,unnecessary-dunder-call
        stubs.append(stub)

    coros = []
    for stub in stubs:
        coro = test_client.call_service(
            stub.List,
            ListApiEndpointsRequest(),
            timeout=60,
            expected_type=ListApiEndpointsResponse,
            auth=False
        )
        coros.append(coro)

    await asyncio.gather(*coros)

    for context in ctx:
        await context.__aexit__(None, None, None)


@pytest.mark.asyncio
async def test_stream_cancel_async(async_sdk, servicers):
    """This tests shows, that after close, call is actually cancelled
    and server handler is stopped its work correctly.
    """
    result = async_sdk.models.completions('foo').run_stream('foo')

    await result.__anext__()  # pylint: disable=unnecessary-dunder-call
    await result.__anext__()  # pylint: disable=unnecessary-dunder-call
    await result.aclose()

    await asyncio.sleep(3)
    assert servicers[0][0].i == 2


def test_stream_cancel_sync(sdk, servicers):
    """This tests shows, that after close, call is actually cancelled
    and server handler is stopped its work correctly.
    """

    result = sdk.models.completions('foo').run_stream('foo')

    next(result)
    next(result)
    result.close()

    time.sleep(3)
    assert servicers[0][0].i == 2
