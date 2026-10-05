class PipelineError(Exception):
    """This is a baseclass for other 4 errors and raised in orchestrator.py, minutes.py, llm_client.py (invalid JSON, empty model reply, "no speech detected") and we built this custom class to specify error to user."""


class AudioError(PipelineError):
    pass 
    # Raised when problem with the audio or video input used in audio.py (empty file, wrong file type, ffmpeg missing, recording too short) and download.py (bad link, playlist, live stream).



class ConfigError(PipelineError):
    pass
    # Raised when bad setup or configuration used in config.py, settings.py and llm_client.py (config file missing, invalid YAML, unknown profile, missing or rejected API key).


class RequestTooLargeError(PipelineError):
    """provider rejected the request because it is too big (HTTP 413 / token-per-minute limit)."""


class ProviderError(PipelineError):
    """Connection problem, timeout or server error that did not go away after retries."""
