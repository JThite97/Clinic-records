import pytest

from clinic.security import Keystore, KeystoreError, hash_password, verify_password


def test_argon2_roundtrip():
    h = hash_password("s3cret-pass")
    assert h.startswith("$argon2id$")
    assert verify_password(h, "s3cret-pass")
    assert not verify_password(h, "wrong")


def test_keystore_wrap_unwrap(tmp_path):
    ks = Keystore(tmp_path / "ks.json")
    key = Keystore.generate_data_key()
    ks.wrap_for("Doc", "password-1", key)
    assert ks.unwrap("doc", "password-1") == key
    with pytest.raises(KeystoreError):
        ks.unwrap("doc", "password-2")
    with pytest.raises(KeystoreError):
        ks.unwrap("nobody", "password-1")
    assert key.hex() not in (tmp_path / "ks.json").read_text()
