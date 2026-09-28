"""TunarrTube/local Music, Music Video, and Other Video interoperability."""

import json

import channel_engine
import export


def test_library_picker_keeps_music_from_the_primary_plex_source(pr, monkeypatch):
    monkeypatch.setattr(pr, "_load_config", lambda: {
        "plex_url": "http://plex",
        "plex_token": "token",
        "tunarr_url": "http://tunarr",
    })
    monkeypatch.setattr(pr, "_plex_get", lambda *args: {
        "MediaContainer": {"Directory": [
            {"key": "1", "title": "Movies", "type": "movie"},
        ]}
    })
    monkeypatch.setattr(pr.channel_engine, "api", lambda *args, **kwargs: [{
        "type": "plex",
        "name": "Primary Plex",
        "uri": "http://plex",
        "libraries": [
            {"id": "movies", "name": "Movies", "mediaType": "movies", "enabled": True},
            {"id": "music", "name": "Albums", "mediaType": "music", "enabled": True},
        ],
    }])

    libraries = pr.list_libraries()

    assert libraries == [
        {"key": "plex:1", "title": "Movies", "type": "movie", "server": "Your Library"},
        {"key": "tunarr:music", "title": "Albums", "type": "music", "server": "Primary Plex"},
    ]


def _wrapper(program_id, title, program_type, **metadata):
    return {
        "type": "content",
        "id": program_id,
        "program": {"title": title, "type": program_type, "state": "ok", **metadata},
    }


def test_local_extra_libraries_index_without_a_plex_source(monkeypatch):
    source = {
        "type": "local",
        "name": "TunarrTube",
        "libraries": [
            {"id": "tracks", "mediaType": "music", "enabled": True},
            {"id": "videos", "mediaType": "music_videos", "enabled": True},
            {"id": "clips", "mediaType": "other_videos", "enabled": True},
        ],
    }
    programs = {
        "tracks": [_wrapper("track-1", "Blue Monday", "track")],
        "videos": [_wrapper("mv-1", "Thriller", "music_video", artistName="Michael Jackson")],
        "clips": [_wrapper("clip-1", "Station Ident", "other_video")],
    }

    def fake_api(url, method, path, body=None, timeout=60):
        if path == "/api/media-sources":
            return [source]
        for library_id, items in programs.items():
            if path.endswith(f"/{library_id}/programs"):
                return items
        raise AssertionError(path)

    monkeypatch.setattr(channel_engine, "api", fake_api)
    movies, shows, extras = channel_engine.build_library_index("http://tunarr")

    assert movies == {}
    assert shows == {}
    assert extras["music"]["blue monday"]["id"] == "track-1"
    assert extras["music_video"]["thriller"]["id"] == "mv-1"
    assert extras["music_video"]["michael jackson — thriller"]["id"] == "mv-1"
    assert extras["other_video"]["station ident"]["id"] == "clip-1"


def test_typed_extra_refs_resolve_to_the_requested_media_type():
    extras = {
        "music": {"shared": _wrapper("track", "Shared", "track")},
        "music_video": {"shared": _wrapper("video", "Shared", "music_video")},
        "other_video": {"shared": _wrapper("other", "Shared", "other_video")},
    }
    resolved, missing = channel_engine.resolve_content(
        [
            {"music": "Shared"},
            {"music_video": "Shared"},
            {"other_video": "Shared"},
        ],
        {},
        {},
        extra_maps=extras,
    )

    assert missing == []
    assert [item["type"] for item in resolved] == ["Music", "Music Video", "Other Video"]
    assert [item["programs"][0]["id"] for item in resolved] == ["track", "video", "other"]


def test_music_tracks_use_a_manual_lineup_that_tunarr_can_schedule():
    items = [{
        "type": "Music",
        "title": "Blue Monday",
        "programs": [_wrapper("track-1", "Blue Monday", "track", duration=456000)],
    }]

    schedule = channel_engine.build_schedule("shuffle", items)

    assert schedule == {
        "type": "manual",
        "lineup": [{"type": "content", "id": "track-1", "duration": 456000}],
        "append": False,
    }


def test_music_video_and_other_video_use_tunarr_movie_slot():
    items = [
        {
            "type": "Music Video",
            "title": "Thriller",
            "programs": [_wrapper("mv-1", "Thriller", "music_video")],
        },
        {
            "type": "Other Video",
            "title": "Station Ident",
            "programs": [_wrapper("other-1", "Station Ident", "other_video")],
        },
    ]

    schedule = channel_engine.build_schedule("shuffle", items)

    assert schedule["type"] == "random"
    assert schedule["programs"] == ["mv-1", "other-1"]
    assert [slot["type"] for slot in schedule["schedule"]["slots"]] == ["movie"]


def test_tunarrtube_music_video_rows_keep_artist_and_album(monkeypatch):
    sources = [{
        "type": "local",
        "name": "TunarrTube",
        "libraries": [{"id": "videos", "mediaType": "music_videos", "enabled": True}],
    }]
    wrappers = [_wrapper(
        "mv-1", "Enjoy the Silence", "music_video",
        artistName="Depeche Mode", albumName="Violator", year=1990,
        genres=[{"name": "Alternative"}],
    )]

    monkeypatch.setattr(
        export,
        "tunarr_get",
        lambda url, path, timeout=60: sources if path == "/api/media-sources" else wrappers,
    )
    movies, shows, media = export.build_extra_rows_from_tunarr(
        "http://tunarr", set(), set(), allowed_movie_libs=set(), allowed_tv_libs=set()
    )

    assert movies == [] and shows == []
    assert media == [{
        "Title": "Enjoy the Silence", "Reference": "Depeche Mode — Enjoy the Silence",
        "Year": 1990, "Type": "Music Video",
        "Rating": "", "Genres": "Alternative", "Director": "", "Studio": "",
        "Actors": "", "Seasons": "", "Episodes": "", "Country": "", "Mood": "",
        "Style": "", "Artist": "Depeche Mode", "Album": "Violator", "Source": "TunarrTube",
    }]


def test_planner_offers_and_composes_extra_media_templates(pr, seed):
    seed([
        {"Title": "Track One", "Type": "Music", "Artist": "Artist"},
        {"Title": "Video One", "Type": "Music Video", "Artist": "Artist"},
        {"Title": "Ident One", "Type": "Other Video"},
    ])

    facets = pr.library_facets()
    assert facets["media_types"] == [
        {"type": "Music", "label": "Music", "count": 1},
        {"type": "Music Video", "label": "Music Video", "count": 1},
        {"type": "Other Video", "label": "Other Video", "count": 1},
    ]

    result = pr.compose_channels(pr.ComposeRequest(
        specs=[pr.CandidateSpec(kind="media_type", value="Music Video")], start=40
    ))
    assert result["ok"] is True
    draft = json.loads(
        (pr._test_data_dir / "channels.draft.json").read_text(encoding="utf-8")
    )
    assert draft["channels"] == [{
        "number": 40,
        "name": "Music Videos",
        "shuffle": "shuffle",
        "content": [{"music_video": "Artist — Video One"}],
    }]
