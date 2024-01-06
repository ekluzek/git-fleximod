#!/usr/bin/env python
import sys
import os
import shutil
import logging
import argparse
from modules import utils
from modules.gitinterface import GitInterface
from modules.gitmodules import GitModules


def commandline_arguments(args=None):
    description = """
    %(prog)s manages checking out groups of gitsubmodules with addtional support for Earth System Models
    """
    parser = argparse.ArgumentParser(
        description=description, formatter_class=argparse.RawDescriptionHelpFormatter
    )

    #
    # user options
    #
    parser.add_argument(
        "components",
        nargs="*",
        help="Specific component(s) to checkout. By default, "
        "all required submodules are checked out.",
    )

    parser.add_argument(
        "-C",
        "--path",
        default=os.getcwd(),
        help="Toplevel repository directory.  Defaults to current directory.",
    )

    parser.add_argument(
        "-g",
        "--gitmodules",
        nargs="?",
        default=".gitmodules",
        help="The submodule description filename. " "Default: %(default)s.",
    )

    parser.add_argument(
        "-x",
        "--exclude",
        nargs="*",
        help="Component(s) listed in the gitmodules file which should be ignored.",
    )

    parser.add_argument(
        "-o",
        "--optional",
        action="store_true",
        default=False,
        help="By default only the required submodules "
        "are checked out. This flag will also checkout the "
        "optional submodules relative to the toplevel directory.",
    )

    parser.add_argument(
        "-S",
        "--status",
        action="store_true",
        default=False,
        help="Output the status of the repositories managed by "
        "%(prog)s. By default only summary information "
        "is provided. Use the verbose option to see details.",
    )

    parser.add_argument(
        "-u",
        "--update",
        action="store_true",
        default=False,
        help="Update submodules to the tags defined in .gitmodules.",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="count",
        default=0,
        help="Output additional information to "
        "the screen and log file. This flag can be "
        "used up to two times, increasing the "
        "verbosity level each time.",
    )

    parser.add_argument(
        "-V",
        "--version",
        action="store_true",
        default=False,
        help="Print manage_externals version and exit.",
    )

    #
    # developer options
    #
    parser.add_argument(
        "--backtrace",
        action="store_true",
        help="DEVELOPER: show exception backtraces as extra " "debugging output",
    )

    parser.add_argument(
        "-d",
        "--debug",
        action="store_true",
        default=False,
        help="DEVELOPER: output additional debugging "
        "information to the screen and log file.",
    )

    logging_group = parser.add_mutually_exclusive_group()

    logging_group.add_argument(
        "--logging",
        dest="do_logging",
        action="store_true",
        help="DEVELOPER: enable logging.",
    )
    logging_group.add_argument(
        "--no-logging",
        dest="do_logging",
        action="store_false",
        default=False,
        help="DEVELOPER: disable logging " "(this is the default)",
    )
    if args:
        options = parser.parse_args(args)
    else:
        options = parser.parse_args()

    if options.optional:
        esmrequired = ("T:T", "T:F", "I:T")
    else:
        esmrequired = ("T:T", "I:T")

    if options.status:
        action = "status"
    elif options.update:
        action = "update"
    else:
        action = "install"

    if options.version:
        version_info = ""
        version_file_path = os.path.join(os.path.dirname(__file__), "version.txt")
        with open(version_file_path) as f:
            version_info = f.readlines()[0].strip()
        print(version_info)
        sys.exit(0)

    return (
        options.path,
        options.gitmodules,
        esmrequired,
        options.components,
        options.exclude,
        options.verbose,
        action,
    )


def submodule_sparse_checkout(name, url, path, sparsefile, tag="master"):
    # first create the module directory
    if not os.path.isdir(path):
        os.makedirs(path)
    # Check first if the module is already defined
    # and the sparse-checkout file exists
    git = GitInterface(os.getcwd())
    topdir = git.git_operation("rev-parse", "--show-toplevel").rstrip()

    topgit = os.path.join(topdir, ".git", "modules")
    gitsparse = os.path.join(topgit, name, "info", "sparse-checkout")
    if os.path.isfile(gitsparse):
        logging.warning("submodule {} is already initialized".format(name))
        return

    # initialize a new git repo and set the sparse checkout flag
    sprepo_git = GitInterface(os.path.join(topdir, path))
    sprepo_git.config_set_value("core", "sparseCheckout", "true")

    # set the repository remote
    sprepo_git.git_operation("remote", "add", "origin", url)

    if not os.path.isdir(topgit):
        os.makedirs(topgit)
    topgit = os.path.join(topgit, name)

    shutil.move(os.path.join(path, ".git"), topgit)

    shutil.copy(os.path.join(path, sparsefile), gitsparse)

    with open(os.path.join(path, ".git"), "w") as f:
        f.write("gitdir: " + os.path.relpath(topgit, path))

    # Finally checkout the repo
    sprepo_git.git_operation("fetch", "--depth=1", "origin", "--tags")
    sprepo_git.git_operation("checkout", tag)
    print(f"Successfully checked out {name}")


def submodule_checkout(root, name, path):
    git = GitInterface(root)
    repodir = os.path.join(root, path)
    git.git_operation("submodule", "update", "--init", path)
    # Look for a .gitmodules file in the newly checkedout repo
    if os.path.exists(os.path.join(repodir, ".gitmodules")):
        # recursively handle this checkout
        print(f"Recursively checking out submodules of {name} {repodir}")
        gitmodules = GitModules(repodir)
        submodules_install(gitmodules, repodir, ("I:T"))
    if os.path.exists(os.path.join(repodir, ".git")):
        print(f"Successfully checked out {name}")
    else:
        utils.fatal_error(f"Failed to checkout {name}")
    return


def submodules_status(gitmodules, root_dir):
    for name in gitmodules.sections():
        path = gitmodules.get(name, "path")
        tag = gitmodules.git(name, "esmtag")
        with utils.pushd(path):
            git = GitInterface(os.path.join(root_dir, path))
            atag = git.git_operation("describe", "--tags", "--always").rstrip()
            if tag and atag != tag:
                print(f"Submodule {name} {atag} is out of sync with .gitmodules {tag}")
            elif tag:
                print(f"Submodule {name} at tag {tag}")
            else:
                print(f"Submodule {name} has no tag defined in .gitmodules")


def submodules_update(gitmodules, root_dir):
    for name in gitmodules.sections():
        esmtag = gitmodules.get(name, "esmtag")
        path = gitmodules.get(name, "path")
        url = gitmodules.get(name, "url")
        if os.path.exists(os.path.join(path, ".git")):
            with utils.pushd(root_dir):
                git = GitInterface(root_dir)
                # first make sure the url is correct
                upstream = git.git_operation("ls-remote", "--get-url").rstrip()
                if upstream != url:
                    # TODO - this needs to be a unique name
                    git.git_operation("remote", "add", "newbranch", url)
                    git.git_operation("checkout", esmtag)


def submodules_install(gitmodules, root_dir, requiredlist):
    for name in gitmodules.sections():
        esmrequired = gitmodules.get(name, "esmrequired")
        esmsparse = gitmodules.get(name, "esmsparse")
        esmtag = gitmodules.get(name, "esmtag")
        path = gitmodules.get(name, "path")
        url = gitmodules.get(name, "url")
        if esmrequired not in requiredlist:
            if "T:F" in esmrequired:
                print("Skipping optional component {}".format(name))
            continue
        if esmsparse:
            submodule_sparse_checkout(name, url, path, esmsparse, tag=esmtag)
        else:
            submodule_checkout(root_dir, name, path)


def _main_func():
    (
        root_dir,
        file_name,
        esmrequired,
        includelist,
        excludelist,
        verbose,
        action,
    ) = commandline_arguments()
    if verbose:
        print(f"action is {action}")
    gitmodules = GitModules(
        confpath=root_dir,
        conffile=file_name,
        includelist=includelist,
        excludelist=excludelist,
    )

    if action == "update":
        submodules_update(gitmodules, root_dir)
    elif action == "install":
        submodules_install(gitmodules, root_dir, esmrequired)
    elif action == "status":
        submodules_status(gitmodules, root_dir)
    else:
        utils.fatal_error(f"unrecognized action request {action}")


if __name__ == "__main__":
    _main_func()
