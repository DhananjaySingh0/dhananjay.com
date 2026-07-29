import json
import os
import tempfile
import threading

from github_sync import fetch_json as _github_fetch_json
from github_sync import push_json as _github_push_json

_LOCK = threading.RLock()


def ensure_dirs(*paths):
    for path in paths:
        os.makedirs(path, exist_ok=True)


def _write_local(path, data):
    """Write JSON to `path` such that readers never see a partial file.

    Local-disk write only - does NOT touch the GitHub backup. Used when
    re-seeding a missing/corrupt file (see load_list): that seed is a
    *placeholder* for this process to have something to read, not a
    confirmed piece of real data, so it must never be pushed to GitHub -
    doing so would silently overwrite a perfectly good backup with an
    empty/default list the moment the local disk happens to be wiped
    (e.g. an ephemeral Render disk) and someone merely loads a page.
    """
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".tmp-", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def _atomic_write(path, data):
    """Write JSON to `path` AND back it up to GitHub - synchronously.

    Use this only for real mutations (add/edit/delete/reorder) - i.e. data
    a person actually asked to save. See _write_local for re-seeding a
    missing/corrupt file, which must not be treated as real data.

    The GitHub push is synchronous (not fire-and-forget) on purpose: if
    there's no persistent disk attached, GitHub is the *only* durable copy
    of the data. An async push races the container's next restart/spin-down
    - if the process dies before the background thread finishes, the write
    never reaches GitHub, and the next request (on a fresh, empty local
    disk) restores the OLD data, silently reverting the change that was
    just confirmed to the browser. Waiting for the push here means the
    request only reports success once GitHub actually has the new data.
    This only affects admin add/edit/delete calls, which are rare, so the
    extra ~200-500ms is a good trade for not losing data. A GitHub outage
    still never raises - push_json is best-effort and returns False rather
    than throwing - so the local write always succeeds either way.
    """
    _write_local(path, data)
    _github_push_json(os.path.basename(path), data)


def load_list(path, default=None):
    """Load a JSON list, seeding the file with `default` on first run.

    If the local file is missing (fresh checkout, or a fresh deploy on an
    ephemeral disk) this first tries to restore the last-known copy from
    GitHub before falling back to `default`.
    """
    default = list(default or [])
    with _LOCK:
        if not os.path.exists(path):
            filename = os.path.basename(path)
            restored = _github_fetch_json(filename)
            seed = restored if isinstance(restored, list) else default
            # Local-only: this seed (restored copy, or empty/default) must
            # never overwrite a good GitHub backup - see _write_local.
            _write_local(path, seed)
            return list(seed)
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, list) else list(default)
        except (json.JSONDecodeError, OSError):
            # Corrupt local file: keep a copy for forensics, then try
            # GitHub before giving up and using defaults.
            try:
                os.replace(path, path + ".corrupt")
            except OSError:
                pass
            filename = os.path.basename(path)
            restored = _github_fetch_json(filename)
            seed = restored if isinstance(restored, list) else default
            # Local-only, same reasoning as above.
            _write_local(path, seed)
            return list(seed)


def save_list(path, items):
    with _LOCK:
        _atomic_write(path, list(items))


def read_modify_write(path, mutator, default=None):
    """Run `mutator(items)` under the lock and persist the result (locally
    and, synchronously, to GitHub - see _atomic_write).

    `mutator` returns (new_items, result); only new_items is written. This
    is the single safe way to mutate a store - use it instead of load+save.
    """
    with _LOCK:
        items = load_list(path, default)
        new_items, result = mutator(items)
        _atomic_write(path, new_items)
        return result
