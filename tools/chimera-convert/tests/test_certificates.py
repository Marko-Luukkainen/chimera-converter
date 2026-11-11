"""Downloads trust the OS's certificates (a machine with HTTPS scanning failed on audio-separator's
first download: CERTIFICATE_VERIFY_FAILED, unable to get local issuer certificate)."""

import ssl


def test_ssl_uses_the_os_trust_store_once_the_package_is_imported():
    import truststore

    import chimera_convert  # noqa: F401

    assert ssl.SSLContext is truststore.SSLContext
    ctx = ssl.create_default_context()
    assert ctx.verify_mode == ssl.CERT_REQUIRED and ctx.check_hostname  # verification stays on
