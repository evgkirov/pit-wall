from pitwall.core.channels import Channel, split_by_target
from pitwall.core.events import Message, Segment, SpeakRequest


def req(*segs, target=None):
    return SpeakRequest(request_id="r1", segments=segs, target=target)


def test_split_groups_by_segment_target_preserving_indices():
    r = req(
        Segment("a", target="mac", index=0),
        Segment("b", target="cloud", index=1),
        Segment("c", target="mac", index=2),
    )
    groups = dict(split_by_target(r))
    assert [s.index for s in groups["mac"].segments] == [0, 2]
    assert [s.index for s in groups["cloud"].segments] == [1]


def test_split_falls_back_to_request_target():
    groups = dict(split_by_target(req(Segment("a", index=0), target="mix")))
    assert list(groups) == ["mix"]


def test_split_targetless_broadcasts_whole_request():
    assert split_by_target(req(Segment("a", index=0))) == [(None, req(Segment("a", index=0)))]


async def test_channel_without_splitter_uses_event_target():
    ch: Channel[Message] = Channel("messages")
    a, b = ch.subscribe("a"), ch.subscribe("b")
    await ch.publish(Message(source="twitch", user="u", text="hi", ts=1.0))
    assert not a.empty() and not b.empty()


async def test_channel_with_splitter_delivers_sub_requests():
    ch: Channel[SpeakRequest] = Channel("speak", splitter=split_by_target)
    mac, cloud = ch.subscribe("mac"), ch.subscribe("cloud")
    await ch.publish(
        req(Segment("a", target="mac", index=0), Segment("b", target="cloud", index=1))
    )
    assert (await mac.get()).segments[0].text == "a"
    assert (await cloud.get()).segments[0].text == "b"


async def test_unsubscribe_stops_delivery():
    ch: Channel[SpeakRequest] = Channel("speak")
    q = ch.subscribe("a")
    ch.unsubscribe("a")
    await ch.publish(req(Segment("a"), target="a"))
    assert q.empty()
