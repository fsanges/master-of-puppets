"""Commands used throughout the GUI."""
import logging
import sys
import time
from mop.custom_scripts import run_scripts


logger = logging.getLogger(__name__)


def reload_mop():
    """Remove all mop modules from the Python session.

    Use this command to reload the `mop` package after
    a change was made.
    """
    import mop.ui

    is_running = mop.ui.is_running()
    mop.ui.close()

    search = ["mop", "shapeshifter", "facseditor"]

    mop_modules = []
    for module in sys.modules:
        for term in search:
            if term in module:
                mop_modules.append(module)
                break

    for module in mop_modules:
        del (sys.modules[module])

    if is_running:
        mop.ui.show()
    logger.info("Reloaded mop modules.")


def open_mop():
    """Open the `mop` GUI."""
    import mop.ui

    mop.ui.close()
    mop.ui.show()


def open_facs_editor():
    """Open the `mop` GUI."""
    import mop.vendor.facseditor as facseditor

    facseditor.close()
    facseditor.show()


def open_parent_spaces():
    """Open the `mop` GUI."""
    import mop.ui.parents

    win = mop.ui.parents.mopParentSpaces()
    win.show()


def build_rig():
    """Build the current scene rig."""
    from mop.core.rig import Rig
    import mop

    mop.incremental_save()
    rig = Rig()
    start_time = time.time()
    run_scripts("build_pre")
    rig.build()
    run_scripts("build_post")
    tot_time = time.time() - start_time
    logger.info("Building the rig took {}s".format(tot_time))


def unbuild_rig():
    """Unbuild the current scene rig."""
    from mop.core.rig import Rig
    import mop

    mop.incremental_save()
    rig = Rig()
    run_scripts("unbuild_pre")
    rig.unbuild()
    run_scripts("unbuild_post")


def publish_rig():
    """Publish the current scene rig."""
    from mop.core.rig import Rig
    import mop

    mop.incremental_save()
    rig = Rig()
    run_scripts("publish_pre")
    rig.publish()
    run_scripts("publish_post")
    mop.save_publish()
    run_scripts("publish_save_post")
