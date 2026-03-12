import glob
import os
import uuid
from unittest.mock import MagicMock, patch

import pytest
from celery.exceptions import Retry


@pytest.fixture()
def tracklist_id():
    return str(uuid.uuid4())


def test_successful_download(tmp_path, tracklist_id):
    audio_file = tmp_path / f"{tracklist_id}.mp3"
    audio_file.write_bytes(b"fake audio")

    mock_ydl_instance = MagicMock()
    mock_ydl_instance.download = MagicMock()
    mock_ydl_class = MagicMock()
    mock_ydl_class.return_value.__enter__ = MagicMock(return_value=mock_ydl_instance)
    mock_ydl_class.return_value.__exit__ = MagicMock(return_value=False)

    with (
        patch("app.tasks.download.settings") as mock_settings,
        patch("app.tasks.download.glob.glob", return_value=[str(audio_file)]),
        patch("yt_dlp.YoutubeDL", mock_ydl_class),
    ):
        mock_settings.RAMDISK_PATH = str(tmp_path)
        from app.tasks.download import download_audio

        result = download_audio.__wrapped__(tracklist_id, "https://soundcloud.com/test")

    assert result["tracklist_id"] == tracklist_id
    assert result["audio_path"] == str(audio_file)
    assert result["url"] == "https://soundcloud.com/test"


def test_download_failure_triggers_retry(tmp_path, tracklist_id):
    mock_retry = MagicMock(side_effect=Retry())

    with (
        patch("app.tasks.download.settings") as mock_settings,
        patch("yt_dlp.YoutubeDL", side_effect=Exception("network error")),
        patch.object(__import__("app.tasks.download", fromlist=["download_audio"]).download_audio, "retry", mock_retry),
    ):
        mock_settings.RAMDISK_PATH = str(tmp_path)
        from app.tasks.download import download_audio

        with pytest.raises(Retry):
            with patch.object(download_audio, "retry", mock_retry):
                download_audio.__wrapped__(tracklist_id, "https://soundcloud.com/fail")

    mock_retry.assert_called_once()


def test_cleanup_on_failure(tmp_path, tracklist_id):
    audio_file = tmp_path / f"{tracklist_id}.mp3"
    audio_file.write_bytes(b"stale audio")

    from app.tasks.download import download_audio

    mock_retry = MagicMock(side_effect=Retry())

    with (
        patch("app.tasks.download.settings") as mock_settings,
        patch("app.tasks.download.glob.glob", return_value=[str(audio_file)]),
        patch("yt_dlp.YoutubeDL", side_effect=Exception("boom")),
        patch.object(download_audio, "retry", mock_retry),
    ):
        mock_settings.RAMDISK_PATH = str(tmp_path)

        with pytest.raises(Retry):
            download_audio.__wrapped__(tracklist_id, "https://soundcloud.com/fail")
