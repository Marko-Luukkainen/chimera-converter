"""Sung recordings + lyrics -> melody files for CHIMERA's `render notes`."""


def _trust_os_certificates() -> None:
    """HTTPS downloads (models) check certificates against the operating system's store, not only
    certifi's list. Antivirus HTTPS scanning and company proxies sign connections with a root the
    OS trusts but certifi doesn't: on such a Windows machine audio-separator's first download
    (raw.githubusercontent.com) failed with CERTIFICATE_VERIFY_FAILED, though Demucs, which reads
    the Windows store, worked. Verification stays on; pip does the same."""
    try:
        import truststore
    except ImportError:
        return
    truststore.inject_into_ssl()


_trust_os_certificates()
