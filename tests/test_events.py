from pitwall.core.events import Audio, Message, Segment, SpeakRequest


def test_message_defaults():
    m = Message(source="twitch", user="alice", text="hi", ts=1.0)
    assert m.kind == "chat" and m.raw is None


def test_segment_defaults():
    s = Segment(text="hi")
    assert s.voice is None and s.target is None and s.index == 0


def test_speak_request_defaults():
    r = SpeakRequest(request_id="r1", segments=(Segment("hi"),))
    assert r.target is None and r.source is None and r.user is None and r.meta is None


def test_audio_defaults():
    a = Audio(path="/tmp/a.aiff", request_id="r1", index=0)
    assert a.source is None and a.user is None
