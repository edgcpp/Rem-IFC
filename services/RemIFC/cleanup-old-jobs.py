# Python 3 Windows Only Script for RemIFC Build Cleanup

# Copyright 2026 Edison Design Group, Inc.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the “Software”), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED “AS IS”, WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

#
# The script checks for directories in 'C:\RemIFC\builds' that are more than a
# day old, and automatically removes them. The script works relatively high
# level with the file system to avoid historically slow(-er) walking of
# directories.
#
# This script should be added as a scheduled task to the Windows "Tasks
# Scheduler" portion of the "Computer Management" interface once the RemIFC
# system and folder structure is in place on the system. The script can be run
# once a day (or more/less frequently if desired).
#

import datetime
import time
import os
import shutil

PATH_TO_BUILDS = 'C:\\RemIFC\\builds\\'
MAX_DIR_LIFETIME = datetime.timedelta(days=1).total_seconds()

def get_orphaned_build_directories():
  '''Returns a list of directories that are more than a day old.'''
  # Store the current time as a constant so we don't recalculate everytime we
  # check a directory (these calls can get expensive).
  cur_time = time.time()

  # Collect build directories that are most definitely orphans that will never
  # be cleaned up otherwise.
  orphaned_build_dirs = []
  for entry in os.listdir(PATH_TO_BUILDS):
    # Combine the entry with the entry's path to get an entry that can be
    # referenced from the current working directory.
    entry_path = os.path.join(PATH_TO_BUILDS, entry)

    # Skip entries that aren't directories.
    if not os.path.isdir(entry_path):
      continue

    time_delta = cur_time - os.path.getmtime(entry_path)

    # Skip directories that haven't yet exceeded the max lifetime.
    if time_delta < MAX_DIR_LIFETIME:
      continue

    orphaned_build_dirs.append(entry_path)

  return orphaned_build_dirs

def main() -> None:
  # Get the list of build directories and remove them in entirety.
  for build_dir in get_orphaned_build_directories():
    shutil.rmtree(build_dir)

main()
