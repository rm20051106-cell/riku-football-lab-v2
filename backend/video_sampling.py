"""Memory-conscious sequential frame sampling helpers."""
def read_sampled_frame(capture, interval: int, first_sample: bool = False):
    """Read frame zero, then advance by interval grabs without random seeking."""
    if first_sample:
        return capture.read()
    for _ in range(max(1, int(interval))):
        if not capture.grab():
            return False, None
    return capture.retrieve()
