"""Signing defect-hunting tests — Task 7.

Cert confirmed from app/certs/ + app/services/signing.py:
  - demo-certificate.p12
  - password: nutrient-demo
"""
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest
import nutrient_sdk
from nutrient_sdk import Document, Signature, DigitalSignatureOptions

from tests.sdk._support import inputs
from tests.sdk._support.markers import defect

CERT = str(Path(__file__).resolve().parent.parent.parent / "app" / "certs" / "demo-certificate.p12")
CERT_PASSWORD = "nutrient-demo"

PROJECT_ENV = str(Path(__file__).resolve().parent.parent.parent / ".env")


def _opts():
    o = DigitalSignatureOptions()
    o.set_certificate_path(CERT)
    o.set_certificate_password(CERT_PASSWORD)
    o.set_signer_name("QA")
    return o


def _run_in_subprocess(body: str) -> subprocess.CompletedProcess:
    """Run an SDK snippet in a FRESH spawned interpreter.

    sign() aborts (SIGABRT) if called in a fork()ed child once nutrient_sdk is
    loaded in the parent (macOS Security.framework fork hostility, see SDK-034).
    A spawned subprocess starts clean, so signing works. Used for tests that
    must perform a real signature under the suite's --forked runner.
    """
    script = textwrap.dedent(f'''
        import os
        from dotenv import load_dotenv
        load_dotenv({PROJECT_ENV!r})
        from nutrient_sdk import License, Document, Signature, DigitalSignatureOptions
        License.register_key(os.environ["NUTRIENT_LICENSE_KEY"])
        CERT = {CERT!r}
        CERT_PASSWORD = {CERT_PASSWORD!r}
    ''') + textwrap.dedent(body)
    return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True)


class TestBaseline:
    def test_sign_and_reopen(self, account_form):
        out = tempfile.mktemp(suffix=".pdf")
        try:
            proc = _run_in_subprocess(f'''
                o = DigitalSignatureOptions()
                o.set_certificate_path(CERT)
                o.set_certificate_password(CERT_PASSWORD)
                o.set_signer_name("QA")
                with Document.open({account_form!r}) as doc, Signature() as signer:
                    signer.sign(doc, {out!r}, o)
            ''')
            assert proc.returncode == 0, proc.stderr
            assert Path(out).stat().st_size > 0
            # Reopening a signed PDF does not invoke the signing path -> fork-safe.
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

    def test_sign_in_forked_child_aborts(self, account_form):
        """SDK-034: with nutrient_sdk loaded in the parent, sign() in a fork()ed
        child aborts (SIGABRT) on macOS (Security.framework fork hostility).
        Other SDK ops survive fork; only signing is affected. Documented, not
        xfail, because it asserts the (problematic) current behavior directly."""
        import os
        out = tempfile.mktemp(suffix=".pdf")
        pid = os.fork()
        if pid == 0:
            try:
                with Document.open(account_form) as doc, Signature() as s:
                    s.sign(doc, out, _opts())
                os._exit(0)
            except BaseException:
                os._exit(2)
        _, status = os.waitpid(pid, 0)
        inputs.cleanup(out)
        # Child terminated by signal (SIGABRT=6): os.WIFSIGNALED true.
        # Fallback: if double-fork changes behavior, assert it did not cleanly exit 0.
        if os.WIFSIGNALED(status):
            assert os.WTERMSIG(status) == 6
        else:
            assert not (os.WIFEXITED(status) and os.WEXITSTATUS(status) == 0), (
                f"Expected child to abort (SIGABRT) but it exited cleanly: status={status}"
            )


class TestSequential:
    def test_sign_then_sign_again(self, account_form):
        out1 = tempfile.mktemp(suffix=".pdf")
        out2 = tempfile.mktemp(suffix=".pdf")
        try:
            p1 = _run_in_subprocess(f'''
                o = DigitalSignatureOptions(); o.set_certificate_path(CERT); o.set_certificate_password(CERT_PASSWORD); o.set_signer_name("QA")
                with Document.open({account_form!r}) as doc, Signature() as s:
                    s.sign(doc, {out1!r}, o)
            ''')
            assert p1.returncode == 0, p1.stderr
            p2 = _run_in_subprocess(f'''
                o = DigitalSignatureOptions(); o.set_certificate_path(CERT); o.set_certificate_password(CERT_PASSWORD); o.set_signer_name("QA")
                with Document.open({out1!r}) as doc, Signature() as s:
                    s.sign(doc, {out2!r}, o)
            ''')
            assert p2.returncode == 0, p2.stderr
            assert Path(out2).read_bytes()[:5].startswith(b"%PDF")
        finally:
            inputs.cleanup(out1, out2)
