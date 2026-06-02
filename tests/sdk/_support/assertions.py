"""Helpers that encode the 'failed cleanly vs crashed/poisoned/silent' judgement."""
import nutrient_sdk


def is_typed_sdk_error(exc: BaseException) -> bool:
    """True if exc is one of the SDK's own typed exceptions."""
    return isinstance(exc, nutrient_sdk.NutrientException)
