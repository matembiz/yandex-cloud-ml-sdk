from __future__ import annotations

from typing_extensions import override

from yandex_cloud_ml_sdk._types.function import BaseModelFunction, ModelTypeT

from .model import AsyncImageGenerationModel, ImageGenerationModel


class BaseImageGeneration(BaseModelFunction[ModelTypeT]):
    @override
    def __call__(
        self,
        model_name: str,
        *,
        model_version: str = 'latest',
    ):
        if '://' in model_name:
            uri = model_name
        else:
            folder_id = self._sdk._folder_id
            uri = f'art://{folder_id}/{model_name}/{model_version}'

        return self._model_type(
            sdk=self._sdk,
            uri=uri,
        )


class ImageGeneration(BaseImageGeneration):
    _model_type = ImageGenerationModel


class AsyncImageGeneration(BaseImageGeneration):
    _model_type = AsyncImageGenerationModel
