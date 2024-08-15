from __future__ import annotations

import asyncio

from yandex_cloud_ml_sdk import AsyncYCloudML


async def main() -> None:
    sdk = AsyncYCloudML(folder_id='b1ghsjum2v37c2un8h64')

    model = sdk.models.text_classifiers('cls://b1ghsjum2v37c2un8h64/bt14f74au2ap3q0f9ou4')

    result = await model.run("foo")

    for prediction in result:
        print(prediction)


if __name__ == '__main__':
    asyncio.run(main())