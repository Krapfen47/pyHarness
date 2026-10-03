from harness import echo


def test_echo() -> None:
    assert echo("hi") == "[harness] hi"
