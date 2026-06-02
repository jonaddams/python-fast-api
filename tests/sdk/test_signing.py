"""Signing defect-hunting tests — Task 7.

Cert confirmed from app/certs/ + app/services/signing.py:
  - demo-certificate.p12
  - password: nutrient-demo
"""
import tempfile
from pathlib import Path

import pytest
import nutrient_sdk
from nutrient_sdk import Document, Signature, DigitalSignatureOptions

from tests.sdk._support import inputs
from tests.sdk._support.markers import defect

CERT = str(Path(__file__).resolve().parent.parent.parent / "app" / "certs" / "demo-certificate.p12")
CERT_PASSWORD = "nutrient-demo"


def _opts():
    o = DigitalSignatureOptions()
    o.set_certificate_path(CERT)
    o.set_certificate_password(CERT_PASSWORD)
    o.set_signer_name("QA")
    return o


class TestBaseline:
    @defect("SDK-034", "signer.sign() crashes (SIGABRT) when called in a forked process whose parent has registered the SDK license")
    def test_sign_and_reopen(self, account_form):
        out = tempfile.mktemp(suffix=".pdf")
        try:
            with Document.open(account_form) as doc, Signature() as signer:
                signer.sign(doc, out, _opts())
            assert Path(out).stat().st_size > 0
            with Document.open(out) as d2:
                assert d2.get_page_count() == 1
        finally:
            inputs.cleanup(out)


class TestEdgeCases:
    def test_options_none_is_typed(self, account_form):
        out = tempfile.mktemp(suffix=".pdf")
        with Document.open(account_form) as doc, Signature() as signer:
            with pytest.raises(nutrient_sdk.NutrientArgumentNullException):
                signer.sign(doc, out, None)
        inputs.cleanup(out)

    def test_missing_cert_path_is_typed(self, account_form):
        out = tempfile.mktemp(suffix=".pdf")
        o = DigitalSignatureOptions()
        o.set_signer_name("QA")
        with Document.open(account_form) as doc, Signature() as signer:
            with pytest.raises(nutrient_sdk.InvalidArgumentException):
                signer.sign(doc, out, o)
        inputs.cleanup(out)

    @defect("SDK-022", "nonexistent cert file raises generic SdkException, not FileNotFoundException")
    def test_nonexistent_cert_is_filenotfound(self, account_form):
        out = tempfile.mktemp(suffix=".pdf")
        o = _opts()
        o.set_certificate_path("/tmp/does-not-exist.p12")
        with Document.open(account_form) as doc, Signature() as signer:
            with pytest.raises(nutrient_sdk.FileNotFoundException):
                signer.sign(doc, out, o)
        inputs.cleanup(out)

    @defect("SDK-020", "set_hash_algorithm(str) raises raw ctypes ArgumentError, not a typed exception")
    def test_hash_algorithm_bad_type_is_typed(self):
        o = DigitalSignatureOptions()
        with pytest.raises(nutrient_sdk.NutrientException):
            o.set_hash_algorithm("SHA256")

    @defect("SDK-021", "Signature use-after-close raises bare ValueError, not InvalidStateException")
    def test_use_after_close_is_typed(self, account_form):
        out = tempfile.mktemp(suffix=".pdf")
        s = Signature()
        s.close()
        with Document.open(account_form) as doc:
            with pytest.raises(nutrient_sdk.InvalidStateException):
                s.sign(doc, out, _opts())
        inputs.cleanup(out)

    @defect("SDK-023", "sign() with None output path raises InitializationError(1002), not a null-arg exception")
    def test_none_output_path_is_null_arg(self, account_form):
        with Document.open(account_form) as doc, Signature() as signer:
            with pytest.raises(nutrient_sdk.NullOrEmptyParameterException):
                signer.sign(doc, None, _opts())


class TestSequential:
    @defect("SDK-034", "signer.sign() crashes (SIGABRT) when called in a forked process whose parent has registered the SDK license")
    def test_sign_then_sign_again(self, account_form):
        out1 = tempfile.mktemp(suffix=".pdf")
        out2 = tempfile.mktemp(suffix=".pdf")
        try:
            with Document.open(account_form) as doc, Signature() as s:
                s.sign(doc, out1, _opts())
            with Document.open(out1) as doc, Signature() as s:
                s.sign(doc, out2, _opts())
            assert Path(out2).read_bytes()[:5].startswith(b"%PDF")
        finally:
            inputs.cleanup(out1, out2)
