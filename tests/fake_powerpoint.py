"""A small stand-in for PowerPoint's object model, for the COM code paths that tests can't run.

Only what powerpoint.place_narrations uses: Slides, Shapes (1-based Item, Count, AddMediaObject2,
Delete), Tags, AnimationSettings.PlaySettings, TimeLine.MainSequence, MediaFormat.Length,
SlideShowTransition and PageSetup.SlideWidth. As in PowerPoint, setting PlayOnEntry adds a media
play effect at the end of the main sequence, started by a click.
"""

from dataclasses import dataclass, field

MEDIA_PLAY = 83
ON_PAGE_CLICK = 1


class FakeTags:
    def __init__(self):
        self.values: dict[str, str] = {}

    def Add(self, name, value):  # noqa: N802 (COM names)
        self.values[name.upper()] = value

    def Item(self, name):  # noqa: N802
        return self.values.get(name.upper(), "")  # PowerPoint returns "" for a missing tag


@dataclass
class FakeTiming:
    TriggerType: int = ON_PAGE_CLICK  # noqa: N815
    TriggerDelayTime: float = 0  # noqa: N815


class FakeEffect:
    def __init__(self, sequence, shape, effect_type):
        self._sequence = sequence
        self.Shape = shape
        self.EffectType = effect_type
        self.Timing = FakeTiming()

    def MoveTo(self, index):  # noqa: N802
        self._sequence.items.remove(self)
        self._sequence.items.insert(index - 1, self)


class FakeSequence:
    def __init__(self):
        self.items: list[FakeEffect] = []

    @property
    def Count(self):  # noqa: N802
        return len(self.items)

    def Item(self, index):  # noqa: N802
        return self.items[index - 1]

    def add(self, shape, effect_type) -> FakeEffect:
        effect = FakeEffect(self, shape, effect_type)
        self.items.append(effect)
        return effect


@dataclass
class FakeTimeLine:
    MainSequence: FakeSequence = field(default_factory=FakeSequence)  # noqa: N815


class FakePlaySettings:
    def __init__(self, shape):
        self._shape = shape
        self._on_entry = 0
        self.HideWhileNotPlaying = 0
        self.adds_effect = True

    @property
    def PlayOnEntry(self):  # noqa: N802
        return self._on_entry

    @PlayOnEntry.setter
    def PlayOnEntry(self, value):  # noqa: N802
        self._on_entry = value
        if value and self.adds_effect:
            self._shape._shapes.slide.TimeLine.MainSequence.add(self._shape, MEDIA_PLAY)


class FakeAnimationSettings:
    def __init__(self, shape):
        self.PlaySettings = FakePlaySettings(shape)


@dataclass
class FakeMediaFormat:
    Length: int = 0  # noqa: N815


class FakeShape:
    _next_id = 1

    def __init__(self, shapes, name, media_path=None, left=0, top=0, length_ms=0):
        self._shapes = shapes
        self.Id = FakeShape._next_id
        FakeShape._next_id += 1
        self.Name = name
        self.media_path = media_path
        self.Left = left
        self.Top = top
        self.Tags = FakeTags()
        self.AnimationSettings = FakeAnimationSettings(self)
        self.MediaFormat = FakeMediaFormat(length_ms)
        self.link_to_file = None
        self.save_with_document = None

    def Delete(self):  # noqa: N802
        self._shapes.items.remove(self)
        sequence = self._shapes.slide.TimeLine.MainSequence
        sequence.items = [effect for effect in sequence.items if effect.Shape is not self]


class FakeShapes:
    def __init__(self, slide, lengths_ms):
        self.slide = slide
        self.items: list[FakeShape] = []
        self._lengths_ms = lengths_ms

    @property
    def Count(self):  # noqa: N802
        return len(self.items)

    def Item(self, index):  # noqa: N802
        return self.items[index - 1]

    def AddMediaObject2(self, path, link, save, left, top):  # noqa: N802
        shape = FakeShape(self, "Media 1", path, left, top, self._lengths_ms.get(path, 0))
        shape.link_to_file, shape.save_with_document = link, save
        self.items.append(shape)
        return shape

    def add(self, name, **kwargs) -> FakeShape:
        shape = FakeShape(self, name, **kwargs)
        self.items.append(shape)
        return shape


@dataclass
class FakeTransition:
    AdvanceOnTime: int = 0  # noqa: N815
    AdvanceOnClick: int = -1  # noqa: N815
    AdvanceTime: float = 0  # noqa: N815
    Hidden: int = 0  # noqa: N815


class FakeSlide:
    def __init__(self, lengths_ms):
        self.Shapes = FakeShapes(self, lengths_ms)
        self.SlideShowTransition = FakeTransition()
        self.TimeLine = FakeTimeLine()


class FakeCollection:
    def __init__(self, items):
        self.items = items

    @property
    def Count(self):  # noqa: N802
        return len(self.items)

    def Item(self, index):  # noqa: N802
        return self.items[index - 1]


@dataclass
class FakePageSetup:
    SlideWidth: float = 960.0  # noqa: N815


@dataclass
class FakeSlideShowSettings:
    AdvanceMode: int = 1  # noqa: N815 (ppSlideShowManualAdvance)


class FakePresentation:
    """slide_count slides; lengths_ms maps an audio path (as given to AddMediaObject2) to ms.

    video_statuses: the CreateVideoStatus values returned one after the other (the last repeats).
    """

    def __init__(self, slide_count, lengths_ms=None, video_statuses=(3,)):
        self.lengths_ms = lengths_ms or {}
        self.Slides = FakeCollection([FakeSlide(self.lengths_ms) for _ in range(slide_count)])
        self.PageSetup = FakePageSetup()
        self.SlideShowSettings = FakeSlideShowSettings()
        self.video_calls = []
        self._video_statuses = list(video_statuses)

    def CreateVideo(self, *args):  # noqa: N802
        self.video_calls.append(args)

    @property
    def CreateVideoStatus(self):  # noqa: N802
        if len(self._video_statuses) > 1:
            return self._video_statuses.pop(0)
        return self._video_statuses[0]

    def slide(self, number) -> FakeSlide:
        return self.Slides.Item(number)
