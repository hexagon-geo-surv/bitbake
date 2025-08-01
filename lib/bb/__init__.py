#
# BitBake Build System Python Library
#
# Copyright (C) 2003  Holger Schurig
# Copyright (C) 2003, 2004  Chris Larson
#
# Based on Gentoo's portage.py.
#
# SPDX-License-Identifier: GPL-2.0-only
#

__version__ = "2.15.1"

import sys
if sys.version_info < (3, 9, 0):
    raise RuntimeError("Sorry, python 3.9.0 or later is required for this version of bitbake")

if sys.version_info < (3, 10, 0):
    # With python 3.8 and 3.9, we see errors of "libgcc_s.so.1 must be installed for pthread_cancel to work"
    # https://stackoverflow.com/questions/64797838/libgcc-s-so-1-must-be-installed-for-pthread-cancel-to-work
    # https://bugs.ams1.psf.io/issue42888
    # so ensure libgcc_s is loaded early on
    import ctypes
    libgcc_s = ctypes.CDLL('libgcc_s.so.1')

class BBHandledException(Exception):
    """
    The big dilemma for generic bitbake code is what information to give the user
    when an exception occurs. Any exception inheriting this base exception class
    has already provided information to the user via some 'fired' message type such as
    an explicitly fired event using bb.fire, or a bb.error message. If bitbake
    encounters an exception derived from this class, no backtrace or other information
    will be given to the user, its assumed the earlier event provided the relevant information.
    """
    pass

import os
import logging
from collections import namedtuple
import multiprocessing as mp

# Python 3.14 changes the default multiprocessing context from "fork" to
# "forkserver". However, bitbake heavily relies on "fork" behavior to
# efficiently pass data to the child processes. Places that need this should do:
#   from bb import multiprocessing
# in place of
#   import multiprocessing

class MultiprocessingContext(object):
    """
    Multiprocessing proxy object that uses the "fork" context for a property if
    available, otherwise goes to the main multiprocessing module. This allows
    it to be a drop-in replacement for the multiprocessing module, but use the
    fork context
    """
    def __init__(self):
        super().__setattr__("_ctx", mp.get_context("fork"))

    def __getattr__(self, name):
        if hasattr(self._ctx, name):
            return getattr(self._ctx, name)
        return getattr(mp, name)

    def __setattr__(self, name, value):
        raise AttributeError(f"Unable to set attribute {name}")

multiprocessing = MultiprocessingContext()


class NullHandler(logging.Handler):
    def emit(self, record):
        pass

class BBLoggerMixin(object):
    def __init__(self, *args, **kwargs):
        # Does nothing to allow calling super() from derived classes
        pass

    def setup_bblogger(self, name):
        if name.split(".")[0] == "BitBake":
            self.debug = self._debug_helper

    def _debug_helper(self, *args, **kwargs):
        return self.bbdebug(1, *args, **kwargs)

    def debug2(self, *args, **kwargs):
        return self.bbdebug(2, *args, **kwargs)

    def debug3(self, *args, **kwargs):
        return self.bbdebug(3, *args, **kwargs)

    def bbdebug(self, level, msg, *args, **kwargs):
        loglevel = logging.DEBUG - level + 1
        if not bb.event.worker_pid:
            if self.name in bb.msg.loggerDefaultDomains and loglevel > (bb.msg.loggerDefaultDomains[self.name]):
                return
            if loglevel < bb.msg.loggerDefaultLogLevel:
                return

        if not isinstance(level, int) or not isinstance(msg, str):
            mainlogger.warning("Invalid arguments in bbdebug: %s" % repr((level, msg,) + args))

        return self.log(loglevel, msg, *args, **kwargs)

    def plain(self, msg, *args, **kwargs):
        return self.log(logging.INFO + 1, msg, *args, **kwargs)

    def verbose(self, msg, *args, **kwargs):
        return self.log(logging.INFO - 1, msg, *args, **kwargs)

    def verbnote(self, msg, *args, **kwargs):
        return self.log(logging.INFO + 2, msg, *args, **kwargs)

    def warnonce(self, msg, *args, **kwargs):
        return self.log(logging.WARNING - 1, msg, *args, **kwargs)

    def erroronce(self, msg, *args, **kwargs):
        return self.log(logging.ERROR - 1, msg, *args, **kwargs)


Logger = logging.getLoggerClass()
class BBLogger(Logger, BBLoggerMixin):
    def __init__(self, name, *args, **kwargs):
        self.setup_bblogger(name)
        super().__init__(name, *args, **kwargs)

logging.raiseExceptions = False
logging.setLoggerClass(BBLogger)

class BBLoggerAdapter(logging.LoggerAdapter, BBLoggerMixin):
    def __init__(self, logger, *args, **kwargs):
        self.setup_bblogger(logger.name)
        super().__init__(logger, *args, **kwargs)

logging.LoggerAdapter = BBLoggerAdapter

logger = logging.getLogger("BitBake")
logger.addHandler(NullHandler())
logger.setLevel(logging.DEBUG - 2)

mainlogger = logging.getLogger("BitBake.Main")

class PrefixLoggerAdapter(logging.LoggerAdapter):
    def __init__(self, prefix, logger):
        super().__init__(logger, {})
        self.__msg_prefix = prefix

    def process(self, msg, kwargs):
        return "%s%s" %(self.__msg_prefix, msg), kwargs

# This has to be imported after the setLoggerClass, as the import of bb.msg
# can result in construction of the various loggers.
import bb.msg

from bb import fetch2 as fetch
sys.modules['bb.fetch'] = sys.modules['bb.fetch2']

# Messaging convenience functions
def plain(*args):
    """
    Prints a message at "plain" level (higher level than a ``bb.note()``).

    Arguments:

    -  ``args``: one or more strings to print.
    """
    mainlogger.plain(''.join(args))

def debug(lvl, *args):
    """
    Prints a debug message.

    Arguments:

    -  ``lvl``: debug level. Higher value increases the debug level
       (determined by ``bitbake -D``).
    -  ``args``: one or more strings to print.
    """
    if isinstance(lvl, str):
        mainlogger.warning("Passed invalid debug level '%s' to bb.debug", lvl)
        args = (lvl,) + args
        lvl = 1
    mainlogger.bbdebug(lvl, ''.join(args))

def note(*args):
    """
    Prints a message at "note" level.

    Arguments:

    -  ``args``: one or more strings to print.
    """
    mainlogger.info(''.join(args))

def verbnote(*args):
    """
    A higher priority note which will show on the console but isn't a warning.

    Use in contexts when something is happening the user should be aware of but
    they probably did something to make it happen.

    Arguments:

    -  ``args``: one or more strings to print.
    """
    mainlogger.verbnote(''.join(args))

#
# Warnings - things the user likely needs to pay attention to and fix
#
def warn(*args):
    """
    Prints a warning message.

    Arguments:

    -  ``args``: one or more strings to print.
    """
    mainlogger.warning(''.join(args))

def warnonce(*args):
    """
    Prints a warning message like ``bb.warn()``, but only prints the message
    once.

    Arguments:

    -  ``args``: one or more strings to print.
    """
    mainlogger.warnonce(''.join(args))

def error(*args, **kwargs):
    """
    Prints an error message.

    Arguments:

    -  ``args``: one or more strings to print.
    """
    mainlogger.error(''.join(args), extra=kwargs)

def erroronce(*args):
    """
    Prints an error message like ``bb.error()``, but only prints the message
    once.

    Arguments:

    -  ``args``: one or more strings to print.
    """
    mainlogger.erroronce(''.join(args))

def fatal(*args, **kwargs):
    """
    Prints an error message and stops the BitBake execution.

    Arguments:

    -  ``args``: one or more strings to print.
    """
    mainlogger.critical(''.join(args), extra=kwargs)
    raise BBHandledException()

def deprecated(func, name=None, advice=""):
    """This is a decorator which can be used to mark functions
    as deprecated. It will result in a warning being emitted
    when the function is used."""
    import warnings

    if advice:
        advice = ": %s" % advice
    if name is None:
        name = func.__name__

    def newFunc(*args, **kwargs):
        warnings.warn("Call to deprecated function %s%s." % (name,
                                                             advice),
                      category=DeprecationWarning,
                      stacklevel=2)
        return func(*args, **kwargs)
    newFunc.__name__ = func.__name__
    newFunc.__doc__ = func.__doc__
    newFunc.__dict__.update(func.__dict__)
    return newFunc

# For compatibility
def deprecate_import(current, modulename, fromlist, renames = None):
    """Import objects from one module into another, wrapping them with a DeprecationWarning"""

    module = __import__(modulename, fromlist = fromlist)
    for position, objname in enumerate(fromlist):
        obj = getattr(module, objname)
        newobj = deprecated(obj, "{0}.{1}".format(current, objname),
                            "Please use {0}.{1} instead".format(modulename, objname))
        if renames:
            newname = renames[position]
        else:
            newname = objname

        setattr(sys.modules[current], newname, newobj)

TaskData = namedtuple("TaskData", [
    "pn",
    "taskname",
    "fn",
    "deps",
    "provides",
    "taskhash",
    "unihash",
    "hashfn",
    "taskhash_deps",
])
