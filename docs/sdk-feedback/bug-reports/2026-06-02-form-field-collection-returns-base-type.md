# Form-field accessors always return base `PdfFormField`, never the typed subtype

| Field | Value |
|---|---|
| **Severity** | High |
| **Priority** | High — typed dispatch is impossible; field-type-specific operations fail |
| **Component** | Python SDK · Forms API (`PdfFormFieldCollection`) |
| **Affects version** | `nutrient-sdk==1.0.6` / `nutrient-sdk-native==1.0.6` (compiled 2026-05-21) |
| **Platform** | macOS 15 (Darwin 25.5.0), ARM64, Apple M4 |
| **Python** | 3.12.13 |
| **Reporter** | Jon Addams (Customer Engineering) |
| **Date** | 2026-06-02 |

## Summary

`PdfFormFieldCollection.__getitem__()` and `find_by_full_name()` always return the base
`PdfFormField` class, even when the underlying field is a text field, checkbox, radio button,
or combo box. The SDK exports typed subclasses (`PdfTextFormField`, `PdfCheckBoxFormField`,
`PdfRadioButtonFormField`, `PdfComboBoxFormField`, etc.) but these are never instantiated by
the collection accessors. Application code cannot dispatch on field type using `isinstance`,
cannot call subtype-specific methods, and cannot distinguish detected field types.

## Steps to reproduce

```python
import os
from dotenv import load_dotenv
load_dotenv(".env")
from nutrient_sdk import License, Document, PdfEditor
License.register_key(os.environ["NUTRIENT_LICENSE_KEY"])

with Document.open("tests/fixtures/account-registration-form.pdf") as doc:
    fields = PdfEditor.edit(doc).get_form_field_collection()
    for i in range(fields.get_count()):
        f = fields[i]
        print(f"field[{i}]: type={type(f).__name__}, field_type={f.get_field_type()}")
```

## Expected behavior

Fields should be returned as their specific subtype. A radio-button field with `get_field_type() == 2`
should be a `PdfRadioButtonFormField` instance; a text field should be `PdfTextFormField`, etc.
`isinstance(field, PdfRadioButtonFormField)` should return `True` for radio fields.

## Actual behavior

```
field[0]: type=PdfFormField, field_type=1
field[1]: type=PdfFormField, field_type=2
field[2]: type=PdfFormField, field_type=1
...
```

Every field returns `type=PdfFormField` regardless of its actual type. The typed subclasses
exist in `nutrient_sdk` but are never used by the collection.

## Impact

- **Type-specific operations** (e.g. `get_options()` on a combo box, `is_checked()` on a
  checkbox) require the correct subtype and cannot be called on the base class.
- **Form-detection output** (`detect_and_add_form_fields`) is similarly untyped — there is no
  way to know whether a detected field is a text box or a checkbox from the returned object.
- **isinstance dispatch** is broken. Applications that try `if isinstance(field, PdfCheckBoxFormField):`
  will always fall through to the base-type branch.

## Workaround

Use `get_field_type()` (returns an int) and manually look up what each int means. There is no
documented mapping of int to field type in the public Python API docs; the int values must be
inferred from experimentation. This is fragile and not self-documenting.

## Root cause hypothesis

The Python binding's collection `__getitem__` and `find_by_full_name` call a native method
that returns the underlying object but do not inspect the type tag to construct the correct
Python subclass. The native layer likely has the type information; the Python layer does not
perform the type coercion step.

## Reproduction artifact

- `tests/sdk/test_forms.py::test_field_is_typed_subtype` (xfail)

```python
@defect("SDK-017", "field is always base PdfFormField, never the typed subtype")
def test_field_is_typed_subtype(self, account_form):
    with Document.open(account_form) as doc:
        fields = PdfEditor.edit(doc).get_form_field_collection()
        radio = fields.find_by_full_name("account_type")
        assert type(radio).__name__ != "PdfFormField"
```

## Suggested fix

In the binding's `__getitem__` / `find_by_full_name` implementation, check `get_field_type()`
on the native return and instantiate the appropriate Python subclass. This is a pure Python-layer
fix — no native changes needed.

## Related

- SDK-012: No public annotation indexer — similar binding omission in a related API.
- SDK-013: `collection[i]` out-of-range raises builtin `IndexError` instead of a typed
  exception — another collection-indexer gap.
