"""Cross-process ownership of disposable render directories."""

import os
from contextlib import contextmanager


@contextmanager
def lease(directory):
    locks = directory.parent / ".locks"
    locks.mkdir(parents=True, exist_ok=True)
    path = locks / (directory.name + ".lock")
    stream = path.open("a+b")
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            if path.stat().st_size == 0:
                stream.write(b"0")
                stream.flush()
            stream.seek(0)
            try:
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
                acquired = True
            except OSError:
                pass
        else:
            import fcntl

            try:
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                acquired = True
            except BlockingIOError:
                pass
        yield acquired
    finally:
        if acquired and os.name == "nt":
            stream.seek(0)
            msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
        stream.close()
        # Keep the small lock file: unlinking it could let two owners lock different inodes.
