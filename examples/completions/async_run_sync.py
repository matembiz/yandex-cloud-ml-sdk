from __future__ import annotations

import time

from yandex_cloud_ml_sdk import YCloudML


def main():
    sdk = YCloudML(folder_id='b1ghsjum2v37c2un8h64')

    model = sdk.models.completions('yandexgpt')

    operation = model.configure(temperature=0.5).run_async("foo")

    status = operation.get_status()
    while status.is_running:
        time.sleep(5)
        status = operation.get_status()

    result = operation.get_result()
    print(result)

    operation = model.configure().run_async("bar")

    result = operation.wait()
    print(result)


if __name__ == '__main__':
    main()
