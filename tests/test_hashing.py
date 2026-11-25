import pytest

from pipeline.hashing import HASH_LEN, canonical_json, hash_file, hash_inputs


def test_same_inputs_same_hash():
    a = {"prompt": "jebena pouring", "seed": 7, "size": [1344, 768]}
    assert hash_inputs(a) == hash_inputs(dict(a))


def test_key_order_does_not_matter():
    assert hash_inputs({"a": 1, "b": 2}) == hash_inputs({"b": 2, "a": 1})


def test_any_change_changes_hash():
    base = {"prompt": "jebena pouring", "seed": 7}
    assert hash_inputs(base) != hash_inputs({**base, "seed": 8})
    assert hash_inputs(base) != hash_inputs({**base, "prompt": "jebena pouring."})


def test_equal_numbers_hash_equal():
    assert hash_inputs({"zoom": 7}) == hash_inputs({"zoom": 7.0})
    assert hash_inputs({"zoom": 1.05}) == hash_inputs({"zoom": 1.0500000001})


def test_bool_is_not_confused_with_int():
    assert hash_inputs({"x": True}) != hash_inputs({"x": 1})


def test_unicode_is_stable():
    text = "ቡና"  # Amharic for coffee
    assert hash_inputs({"text": text}) == hash_inputs({"text": text})
    assert "ቡና" in canonical_json({"text": text})


def test_hash_length():
    assert len(hash_inputs({"a": 1})) == HASH_LEN


def test_unhashable_type_is_rejected():
    with pytest.raises(TypeError):
        hash_inputs({"a": object()})


def test_hash_file_tracks_content(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"abc")
    first = hash_file(f)
    f.write_bytes(b"abd")
    assert hash_file(f) != first
    assert len(first) == HASH_LEN
