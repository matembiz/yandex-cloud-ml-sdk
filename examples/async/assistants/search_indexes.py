#!/usr/bin/env python3

from __future__ import annotations

import asyncio
import pathlib

from yandex_cloud_ml_sdk import AsyncYCloudML
from yandex_cloud_ml_sdk.search_indexes import StaticIndexChunkingStrategy, TextSearchIndexType


def local_path(path: str) -> pathlib.Path:
    return pathlib.Path(__file__).parent / path


async def main() -> None:
    sdk = AsyncYCloudML(
        folder_id='b1ghsjum2v37c2un8h64',
        service_map={
            'ai-files': 'assistant.api.cloud.yandex.net',
            'ai-assistants': 'assistant.api.cloud.yandex.net',
            'operation': 'assistant.api.cloud.yandex.net',
        }
    )

    file_coros = (
        sdk.files.upload(
            local_path(path),
            ttl_days=5,
            expiration_policy="static",
        )
        for path in ['turkey_example.txt', 'maldives_example.txt']
    )
    files = await asyncio.gather(*file_coros)

    operation = await sdk.search_indexes.create_deferred(
        files,
        index_type=TextSearchIndexType(
            chunking_strategy=StaticIndexChunkingStrategy(
                max_chunk_size_tokens=700,
                chunk_overlap_tokens=300,
            )
        )
    )
    search_index = await operation.wait()
    print(f"new {search_index=}")

    search_index2 = await sdk.search_indexes.get(search_index.id)
    print(f"same as first, {search_index2=}")

    await search_index.update(name="foo")
    print(f"now with a name {search_index=}")

    # NB: it doesn't work at the moment
    # index_files = [file async for file in search_index.list_files()]
    # print(f"search index files: {index_files}")
    # index_file = await search_index.get_file(index_files[0].id)
    # print(f"search index file: {index_file}")

    for file in files:
        await file.delete()

    async for search_index in sdk.search_indexes.list():
        print(f"delete {search_index=}")
        await search_index.delete()


if __name__ == '__main__':
    asyncio.run(main())
