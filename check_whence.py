#!/usr/bin/python3

import os, re, stat, sys, subprocess
from io import open


def list_whence():
    with open("WHENCE", encoding="utf-8") as whence:
        for line in whence:
            match = re.match(r'(?:RawFile|File|Source):\s*"(.*)"', line)
            if match:
                yield match.group(1)
                continue
            match = re.match(r"(?:RawFile|File|Source):\s*(\S*)", line)
            if match:
                yield match.group(1)
                continue
            match = re.match(
                r"Licen[cs]e: (?:.*\bSee (.*) for details\.?|(\S*))\n", line
            )
            if match:
                if match.group(1):
                    for name in re.split(r", | and ", match.group(1)):
                        yield name
                    continue
                if match.group(2):
                    # Just one word - may or may not be a filename
                    if not re.search(
                        r"unknown|distributable", match.group(2), re.IGNORECASE
                    ):
                        yield match.group(2)
                        continue


def list_whence_files():
    with open("WHENCE", encoding="utf-8") as whence:
        for line in whence:
            match = re.match(r"(?:RawFile|File):\s*(.*)", line)
            if match:
                yield match.group(1).replace(r"\ ", " ").replace('"', "")
                continue


def list_links_list():
    with open("WHENCE", encoding="utf-8") as whence:
        for line in whence:
            match = re.match(r"Link:\s*(.*)", line)
            if match:
                linkname, target = match.group(1).split("->")

                linkname = linkname.strip().replace(r"\ ", " ").replace('"', "")
                target = target.strip().replace(r"\ ", " ").replace('"', "")

                # Link target is relative to the link
                target = os.path.join(os.path.dirname(linkname), target)
                target = os.path.normpath(target)

                yield (linkname, target)
                continue


def list_git():
    try:
        subprocess.check_output(['git', 'rev-parse', '--is-inside-work-tree'], stderr=subprocess.STDOUT)
        with os.popen("git ls-files") as git_files:
            for line in git_files:
                yield line.rstrip("\n")
    except subprocess.CalledProcessError:
        return None


def list_dir():
    pwd = os.getcwd()
    # Parse every directory to create set of files to be matched with WHENCE entries
    for root, dirs, files in os.walk(pwd):
        for file in files:
            yield os.path.relpath(os.path.join(root, file.rstrip("\n")), pwd)


def main():
    ret = 0
    whence_list = list(list_whence())
    whence_files = list(list_whence_files())
    links_list = list(list_links_list())
    whence_links = list(zip(*links_list))[0]
    known_files = set(name for name in whence_list if not name.endswith("/")) | set(
        [
            ".codespell.cfg",
            ".editorconfig",
            ".gitignore",
            ".gitlab-ci.yml",
            ".pre-commit-config.yaml",
            "Dockerfile",
            "Makefile",
            "README.md",
            "WHENCE",
            "build_packages.py",
            "check_whence.py",
            "contrib/process_linux_firmware.py",
            "contrib/templates/debian.changelog",
            "contrib/templates/debian.control",
            "contrib/templates/debian.copyright",
            "contrib/templates/rpm.spec",
            "copy-firmware.sh",
            "dedup-firmware.sh",
        ]
    )
    known_prefixes = set(name for name in whence_list if name.endswith("/"))
    files_set = set(list_git())
    # If it is not git repo call list_dir()
    if not files_set:
        files_set = set(list_dir())
    executable_files = set(
        [
            "build_packages.py",
            "carl9170fw/genapi.sh",
            "carl9170fw/autogen.sh",
            "check_whence.py",
            "contrib/process_linux_firmware.py",
            "copy-firmware.sh",
            "dedup-firmware.sh",
        ]
    )

    for name in set(name for name in whence_files if name.endswith("/")):
        sys.stderr.write("E: %s listed in WHENCE as File, but is directory\n" % name)
        ret = 1

    for name in set(name for name in whence_files if whence_files.count(name) > 1):
        sys.stderr.write("E: %s listed in WHENCE twice\n" % name)
        ret = 1

    for name in set(link for link in whence_links if whence_links.count(link) > 1):
        sys.stderr.write("E: %s listed in WHENCE twice\n" % name)
        ret = 1

    for name in set(file for file in whence_files if os.path.islink(file)):
        sys.stderr.write("E: %s listed in WHENCE as File, but is a symlink\n" % name)
        ret = 1

    for name in set(link[0] for link in links_list if os.path.islink(link[0])):
        sys.stderr.write("E: %s listed in WHENCE as Link, is in tree\n" % name)
        ret = 1

    invalid_targets = set(link[0] for link in links_list)
    for link, target in sorted(links_list):
        if target in invalid_targets:
            sys.stderr.write(
                "E: target %s of link %s is also a link\n" % (target, link)
            )
            ret = 1

    for name in sorted(list(known_files - files_set) if len(files_set) else list()):
        sys.stderr.write("E: %s listed in WHENCE does not exist\n" % name)
        ret = 1

    # A link can point to a file...
    valid_targets = set(files_set)

    # ... or to a directory
    for target in set(valid_targets):
        dirname = target
        while True:
            dirname = os.path.dirname(dirname)
            if dirname == "":
                break
            valid_targets.add(dirname)

    for link, target in sorted(links_list if len(files_set) else list()):
        if target not in valid_targets:
            sys.stderr.write(
                "E: target %s of link %s in WHENCE does not exist\n" % (target, link)
            )
            ret = 1

    for name in sorted(list(files_set - known_files)):
        # Ignore subdirectory changelogs and GPG detached signatures
        if name.endswith("/ChangeLog") or (
            name.endswith(".asc") and name[:-4] in known_files
        ):
            continue

        # Ignore unknown files in known directories
        for prefix in known_prefixes:
            if name.startswith(prefix):
                break
        else:
            sys.stderr.write("E: %s not listed in WHENCE\n" % name)
            ret = 1

    for name in sorted(list(executable_files)):
        mode = os.stat(name).st_mode
        if not (mode & stat.S_IXUSR and mode & stat.S_IXGRP and mode & stat.S_IXOTH):
            sys.stderr.write("E: %s is missing execute bit\n" % name)
            ret = 1

    for name in sorted(list(files_set - executable_files)):
        mode = os.stat(name).st_mode
        if stat.S_ISDIR(mode):
            if not (
                mode & stat.S_IXUSR and mode & stat.S_IXGRP and mode & stat.S_IXOTH
            ):
                sys.stderr.write("E: %s is missing execute bit\n" % name)
                ret = 1
        elif stat.S_ISREG(mode):
            if mode & stat.S_IXUSR or mode & stat.S_IXGRP or mode & stat.S_IXOTH:
                sys.stderr.write("E: %s incorrectly has execute bit\n" % name)
                ret = 1
        else:
            sys.stderr.write("E: %s is neither a directory nor regular file\n" % name)
            ret = 1

    return ret


if __name__ == "__main__":
    sys.exit(main())
