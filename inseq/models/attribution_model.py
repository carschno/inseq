from typing import Any, List, NoReturn, Optional, Sequence, Tuple, Union, overload

from abc import ABC, abstractmethod

import torch

from ..attr.feat.feature_attribution import FeatureAttribution
from ..data import (
    BatchEncoding,
    FeatureAttributionSequenceOutput,
    ModelIdentifier,
    OneOrMoreFeatureAttributionSequenceOutputs,
    OneOrMoreIdSequences,
    OneOrMoreTokenSequences,
    TextInput,
)
from ..utils import LengthMismatchError, MissingAttributionMethodError
from .model_decorators import unhooked


class AttributionModel(ABC):
    def __init__(self, attribution_method: Optional[str] = None, **kwargs) -> NoReturn:
        if not hasattr(self, "model"):
            self.model = None
        self.attribution_method = None
        self.is_hooked = False
        self.attribution_method = self.get_attribution_method(attribution_method)
        self.setup(**kwargs)

    def setup(self, **kwargs) -> NoReturn:
        """Move the model to device and in eval mode."""
        self.device = torch.device("cuda:0" if torch.cuda.is_available() else "cpu")
        if self.model:
            self.model.to(self.device)
            self.model.eval()
            self.model.zero_grad()

    @staticmethod
    def load(
        model_name_or_path: ModelIdentifier,
        attribution_method: Optional[str] = None,
        **kwargs,
    ):
        return load(model_name_or_path, attribution_method, **kwargs)

    def get_attribution_method(
        self,
        method: Optional[str] = None,
        override_default_attribution: Optional[bool] = False,
    ) -> FeatureAttribution:
        # No method present -> missing method error
        if not method:
            if not self.attribution_method:
                raise MissingAttributionMethodError()
        else:
            if self.attribution_method:
                self.attribution_method.unhook()
            # If either the default method is missing or the override is set,
            # set the default method to the given method
            if override_default_attribution or not self.attribution_method:
                self.attribution_method = FeatureAttribution.load(
                    method, attribution_model=self
                )
            # Temporarily use the current method without overriding the default
            else:
                return FeatureAttribution.load(method, attribution_model=self)
        return self.attribution_method

    def format_input_texts(
        self,
        texts: TextInput,
        ref_texts: Optional[TextInput] = None,
    ) -> Tuple[List[str], List[str]]:
        texts = [texts] if isinstance(texts, str) else texts
        reference_texts = [ref_texts] if isinstance(ref_texts, str) else ref_texts
        if reference_texts and len(texts) != len(reference_texts):
            raise LengthMismatchError(
                "Length mismatch for texts and reference_texts."
                "Input length: {}, reference length: {} ".format(
                    len(texts), len(reference_texts)
                )
            )
        return texts, reference_texts

    @overload
    def attribute(
        self,
        texts: str,
        reference_texts: Optional[TextInput] = None,
        method: Optional[str] = None,
        override_default_method: Optional[bool] = False,
        attr_pos_start: Optional[int] = 1,
        attr_pos_end: Optional[int] = None,
        **kwargs,
    ) -> FeatureAttributionSequenceOutput:
        ...

    @overload
    def attribute(
        self,
        texts: Sequence[str],
        reference_texts: Optional[TextInput] = None,
        method: Optional[str] = None,
        override_default_method: Optional[bool] = False,
        attr_pos_start: Optional[int] = 1,
        attr_pos_end: Optional[int] = None,
        **kwargs,
    ) -> List[FeatureAttributionSequenceOutput]:
        ...

    def attribute(
        self,
        texts: TextInput,
        reference_texts: Optional[TextInput] = None,
        method: Optional[str] = None,
        override_default_attribution: Optional[bool] = False,
        attr_pos_start: Optional[int] = 1,
        attr_pos_end: Optional[int] = None,
        **kwargs,
    ) -> OneOrMoreFeatureAttributionSequenceOutputs:
        """Perform attribution for one or multiple texts."""
        if not texts:
            return []
        texts, reference_texts = self.format_input_texts(texts, reference_texts)
        if not reference_texts:
            texts = self.encode_texts(texts, return_baseline=True)
            generation_args = kwargs.pop("generation_args", {})
            reference_texts = self.generate(
                texts, return_generation_output=False, **generation_args
            )
        attribution_method = self.get_attribution_method(
            method, override_default_attribution
        )
        attribution_args = kwargs.pop("attribution_args", {})
        attribution_args.update(attribution_method.get_attribution_args(**kwargs))
        return attribution_method.prepare_and_attribute(
            texts,
            reference_texts,
            attr_pos_start=attr_pos_start,
            attr_pos_end=attr_pos_end,
            **attribution_args,
        )

    @abstractmethod
    def score_func(self, **kwargs) -> torch.Tensor:
        pass

    @unhooked
    @abstractmethod
    def generate(
        self,
        encodings: BatchEncoding,
        return_generation_output: Optional[bool] = False,
        **kwargs,
    ) -> Union[List[str], Tuple[List[str], Any]]:
        pass

    @abstractmethod
    def encode_texts(self, texts: TextInput, *args) -> BatchEncoding:
        pass

    @abstractmethod
    def convert_ids_to_tokens(
        self, ids: torch.Tensor, skip_special_tokens: Optional[bool] = True
    ) -> OneOrMoreTokenSequences:
        pass

    @abstractmethod
    def convert_tokens_to_ids(
        self,
        tokens: Union[List[str], List[List[str]]],
    ) -> OneOrMoreIdSequences:
        pass


def load(
    model_name_or_path: ModelIdentifier,
    attribution_method: Optional[str] = None,
    **kwargs,
):
    from .huggingface_model import HuggingfaceModel

    from_hf = kwargs.pop("from_hf", None)
    if from_hf:
        return HuggingfaceModel(model_name_or_path, attribution_method, **kwargs)
    else:  # Default behavior is using Huggingface
        return HuggingfaceModel(model_name_or_path, attribution_method, **kwargs)