# Python 3 Windows Only Script for Building IFC Files

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
# For this script to work, EDG_IFC_COMPILER_DEFINITIONS should be set to
# a json file containing supported IFC version targets.
#
# An example JSON config follows:
#
# {
#   "aliases": {
#     "latest": "0.33+"
#   },
#   "targets": {
#     "0.33+": {
#       "architectures": {
#         "x86": {
#           "compiler_path": "C:\\Program Files\\Microsoft Visual Studio\\2022\\Preview\\VC\\Tools\\MSVC\\14.30.30528\\bin\\Hostx86\\x86\\cl.exe",
#           "vcvars_path": "C:\\Program Files\\Microsoft Visual Studio\\2022\\Preview\\VC\\Auxiliary\\Build\\vcvars32.bat",
#           "bin_path": "C:\\Program Files\\Microsoft Visual Studio\\2022\\Preview\\VC\\Tools\\MSVC\\14.30.30528\\bin\\Hostx86\\x86",
#           "inc_path": "C:\\cygwin64\\home\\calebs\\msvs\\latest\\inc",
#           "ifc_path": "C:\\cygwin64\\home\\calebs\\msvs\\latest\\ifc\\x86"
#         },
#         "x64": {
#           "compiler_path": "C:\\Program Files\\Microsoft Visual Studio\\2022\\Preview\\VC\\Tools\\MSVC\\14.30.30528\\bin\\Hostx64\\x64\\cl.exe",
#           "vcvars_path": "C:\\Program Files\\Microsoft Visual Studio\\2022\\Preview\\VC\\Auxiliary\\Build\\vcvars64.bat",
#           "bin_path": "C:\\Program Files\\Microsoft Visual Studio\\2022\\Preview\\VC\\Tools\\MSVC\\14.30.30528\\bin\\Hostx64\\x64",
#           "inc_path": "C:\\cygwin64\\home\\calebs\\msvs\\latest\\inc\\",
#           "ifc_path": "C:\\cygwin64\\home\\calebs\\msvs\\latest\\ifc\\x64"
#         }
#       },
#       "default_architecture": "x86",
#       "extra_flags": [
#         {
#           "flag": "/ifcOnly:edg",
#           "incompatible_with": [
#             "/module:merge"
#           ]
#         }
#       ]
#     }
#   }
# }
#
# The top level is split between aliases and "concrete" targets.
#
# Aliases are key value pairs giving an alternative spec label (what's selected
# by /spec) to a target.
#
# Targets list the "concrete" spec labels. Each key value pair in targets
# defines the architectures map and a default architecture, and a list of extra
# flags to be applied to the command line compiler invocations when building
# with this spec. The default architecture must be a key in the map of default
# architectures.
#
# The inner target architectures map should map an architecture label (what's
# selected by /arch) to the paths for the compiler and vcvars to be used, along
# with the bin (prepended to PATH), inc (prepended to INCLUDE), and ifc
# (prepended to IFCPATH) paths.
#
# The inner target extra flags should be a list of objects defining the flag to
# be added ("flag"), and a list of any incompatible flags. If the text of any
# associated incompatible flags is encountered, the flag will be skipped and a
# warning will be printed. As an example, in the above config for "0.33+",
# "/ifcOnly" will be added to all tests that don't have a "/module:merge" flag
# already specified.
#
# The script builds ifcspec files of the following format:
#
# BUILD_ARGS=/std:c++latest /Wv:18 /experimental:module /EHsc -module:export -module:name lib /c lib.cpp /link
# REQUIRES_FILES=lib.cpp
# MOD_OUTPUT_DIRS=testdir
#
# BUILD_ARGS      - the required argument set to build.
# REQUIRES_FILES  - the space separated set of dependent ifcspecs and
#                   other files that should be present when building this IFC.
# MOD_OUTPUT_DIRS - the optional space separated set of directories to be
#                   created for compatibility with /module:output
#                   (and related) flags.
#
# ifcspec files conventionally use the first file built in BUILD_ARGS as their
# name, e.g. the above would be 'lib.cpp.ifcspec'.
#
# ifcspec files can also optionally contain comments on lines starting with
# '#'.
#

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile

from contextlib import redirect_stdout
from pathlib import Path

SCRIPT_MODIFICATION_DATE=os.path.getmtime(os.path.abspath(__file__))

KEY_VALUE_BASIC_REGEX_STR = '^([A-Z0-9_]+)=(.*)'
KEY_VALUE_REGEX = re.compile(KEY_VALUE_BASIC_REGEX_STR)
ENV_LINE_REGEX = re.compile(f"{KEY_VALUE_BASIC_REGEX_STR}?\r", re.MULTILINE)

class CompilerTargetArchitecture:
  '''Represents a compiler target's internal architecture information.'''

  def __init__(self, *, compiler_path, vcvars_path,
               bin_path, inc_path, ifc_path):
    self.compiler_path = compiler_path
    self.vcvars_path = vcvars_path
    self.bin_path = bin_path
    self.inc_path = inc_path
    self.ifc_path = ifc_path

class CompilerTargetExtraFlag:
  '''Represents a compiler target's internal extra flag information.'''

  def __init__(self, *, flag, incompatible_with):
    self.flag = flag
    self.incompatible_with = incompatible_with

  def check_for_incompatibility(self, current_args):
    '''Takes a list of current arguments, returns the first incompatibility.'''
    for arg in current_args:
      for incompatible_arg in self.incompatible_with:
        if incompatible_arg in arg:
          return incompatible_arg

    return None

class CompilerTarget:
  '''Represents and provides an high level compiler target API'''

  def __init__(self, *, architectures, default_architecture, extra_flags):
    self.default_architecture = default_architecture
    self._architectures = architectures
    self.extra_flags = extra_flags

  def _to_architecture_key(self, architecture):
    '''Converts an architecture string to the architecture set lookup key.

    This should be used prior to accessing the architectures dictionary as it
    handles translation of the "default" architecture to the corresponding key.
    '''
    if architecture == 'default':
      architecture = self.default_architecture
    return architecture

  def supports_architecture(self, architecture):
    '''Returns True if the architecture is supported by this target.'''
    return self._to_architecture_key(architecture) in self._architectures

  def get_supported_architectures(self):
    return self._architectures.keys()

  def _get_arch_info(self, architecture):
    '''Returns the architecture dictionary value for the key.'''
    architecture_key = self._to_architecture_key(architecture)
    return self._architectures[architecture_key]

  def get_compiler(self, architecture):
    '''Returns the compiler executable path.'''
    return self._get_arch_info(architecture).compiler_path

  def get_vcvars_path(self, architecture):
    '''Returns the vcvars script path.'''
    return self._get_arch_info(architecture).vcvars_path

  def _get_bin_path(self, architecture):
    '''Returns the associated PATH environment variable entry.'''
    return self._get_arch_info(architecture).bin_path

  def get_inc_path(self, architecture):
    '''Returns the associated INCLUDES environment variable entry.'''
    return self._get_arch_info(architecture).inc_path

  def get_ifc_path(self, architecture):
    '''Returns the associated IFCPATH environment variable entry.'''
    return self._get_arch_info(architecture).ifc_path

  def _get_environment_cache_path(self, vcvars_path):
    '''Returns the path to the environment cache for a given vcvars.'''
    path_hash = hashlib.md5(vcvars_path.encode('utf-8')).hexdigest()
    return Path(os.path.join(Path.home(), '.remifc', f"{path_hash}.json"))

  def _get_cached_environment(self, cache_path, vcvars_path):
    '''Returns the cached environment dictionary if it exists.'''
    if not os.path.exists(cache_path):
      return None

    # Check the validity of the cache based on modification times.
    last_cache_modification = os.path.getmtime(cache_path)

    # If the vcvars file has been updated, invalidate the cache.
    if last_cache_modification < os.path.getmtime(vcvars_path):
      return None
    # If the script was modified, invalidate the cache.
    if last_cache_modification < SCRIPT_MODIFICATION_DATE:
      return None

    return load_json_file(cache_path)

  # Taken from edgy's create_env_diff.
  def _create_env_diff(self, new_env):
    '''Returns a dictionary of environment variables that are modified.'''
    env_diff = {}
    for key, value in new_env.items():
      # Skip keys already in the environment with the same value.
      if key in os.environ:
        if os.environ[key] == value:
          continue

      # Record the overridden value.
      env_diff[key] = value

    return env_diff

  def _save_as_cached_environment(self, cache_path, env):
    '''Save the environment diff to the given cache path.'''
    # Create a temporary file and then make that file the cache file this
    # prevents cases of files getting garbled from race conditions.
    handle, temp_path = tempfile.mkstemp()
    with os.fdopen(handle, 'w') as tmp_file:
      json.dump(env, tmp_file)
    # Make sure the parent directory exists.
    os.makedirs(cache_path.parent, exist_ok=True)
    # Move the temporary file into the destination.
    os.replace(temp_path, cache_path)

  def _get_vcvars_env(self, architecture):
    '''Returns the vcvars environment before path modifications are applied.'''
    vcvars_path = self.get_vcvars_path(architecture)

    # Check for an up to date cache.
    cache_path = self._get_environment_cache_path(vcvars_path)
    cached_env = self._get_cached_environment(cache_path, vcvars_path)
    if cached_env is not None:
      return cached_env

    # Run the process with captured output.
    completed_process = subprocess.run(
      [
        'cmd.exe', '/c',
        # Equivalent to: "call vcvars.bat && set".
        #
        # Note that while these should conceptually be one argument, Python's
        # argument escaping rules for Windows seem to be hostile, and
        # will place escapes in the wrong places breaking things.
        'call', vcvars_path, '&&', 'set'
      ], capture_output=True
    )
    output_text = completed_process.stdout.decode(errors = 'backslashreplace')

    # Since we have output from executing vcvars, scan using regex specifically
    # for ENV vars.
    env = {}
    for env_line_match in ENV_LINE_REGEX.finditer(output_text):
      env_key = env_line_match[1]
      env_value = env_line_match[2]
      env[env_key] = env_value

    # Only keep the differences.
    env = self._create_env_diff(env)

    # Update the cache so we don't have to do this again unless something
    # changes.
    self._save_as_cached_environment(cache_path, env)

    return env

  def _taint_env_key(self, env, key, new_value, *, overwrite=False):
    '''Update the given environment dictionary's key with a new value.

    If the key is already present in the environment (and we're not forcing an
    overwrite), prepend the new value, if it doesn't exist, set it as the sole
    value.
    '''
    if not overwrite and key in env:
      env[key] = f"{new_value};{env[key]}"
    else:
      env[key] = new_value

  def _taint_env(self, env, architecture):
    '''Modifies various PATH-esk variables based on the configuration.'''
    self._taint_env_key(env, 'PATH', self._get_bin_path(architecture))
    self._taint_env_key(env, 'INCLUDE', self.get_inc_path(architecture))
    # As of Visual Studio 2019, this is not process properly when the path is
    # composed of multiple ';' separated components.
    self._taint_env_key(
      env, 'IFCPATH', self.get_ifc_path(architecture), overwrite=True
    )

  def get_environment(self, architecture):
    '''Return the complete environment for execution of this target.'''
    # Retrieve the pure vcvars environment modifications which are cached
    # across all shared configurations.
    env = self._get_vcvars_env(architecture)
    # Apply some EDG ENV changes to force binaries, IFCs, and headers to be
    # resolved as we desire.
    self._taint_env(env, architecture)
    # Create a merged environment diff with priority to the overrides.
    return (os.environ | env)

def load_json_file(path):
  '''Load a given JSON file as a Python object.'''
  try:
    with open(path, 'r') as json_file:
      return json.loads(json_file.read())
  except json.JSONDecodeError as ex:
    print(
      'Error, invalid JSON. Try linting the JSON '
      '(e.g. "https://jsonlint.com/")'
    )
    raise ex

# FIXME: Type hints can be used to make this even more automatic

def create_compiler_target_architectures(compiler_target_dict):
  '''Convert architectures into CompilerTargetArchitectures objects.'''
  architectures_raw = compiler_target_dict['architectures']
  architectures = {}
  for arch, compiler_targ_arch_dict in architectures_raw.items():
    architectures[arch] = CompilerTargetArchitecture(**compiler_targ_arch_dict)
  # Update the compiler target dict with the CompilerTargetArchitecture objects
  compiler_target_dict['architectures'] = architectures

def create_compiler_target_extra_flags(compiler_target_dict):
  '''Convert extra flags into CompilerTargetExtraFlags objects.'''
  extra_flags_raw = compiler_target_dict['extra_flags']
  extra_flags = []
  for extra_flag_dict in extra_flags_raw:
    extra_flags.append(CompilerTargetExtraFlag(**extra_flag_dict))
  # Update the compiler target dict with the CompilerTargetExtraFlag objects
  compiler_target_dict['extra_flags'] = extra_flags

def create_compiler_target(compiler_target_dict):
  '''Convert the given dict into a CompilerTarget object.'''
  create_compiler_target_architectures(compiler_target_dict)
  create_compiler_target_extra_flags(compiler_target_dict)
  return CompilerTarget(**compiler_target_dict)

def load_compiler_targets():
  '''Load compiler targets from the environmentally specified JSON file.'''
  # Find the compiler definitions path from the environment. We could instead
  # search upwards in the file system for a "compilers.json" or something, but
  # Windows file system walking is typically quite slow.
  compiler_targets_path = os.environ['EDG_IFC_COMPILER_DEFINITIONS']
  parsed_json = load_json_file(compiler_targets_path)

  # Take the loaded JSON object and construct compiler targets from it.
  compiler_targets = {}
  for target_name, compiler_target_dict in parsed_json['targets'].items():
    compiler_targets[target_name] = create_compiler_target(
      compiler_target_dict
    )

  # Load aliases, mapping back to a compiler target.
  for alias_name, compiler_target_name in parsed_json['aliases'].items():
    compiler_targets[alias_name] = compiler_targets[compiler_target_name]

  return compiler_targets

def parse_args():
  '''Parse the commandline arguments for this script.'''
  parser = argparse.ArgumentParser(description='EDG IFC Build Tool.',
                                   prefix_chars='/')
  parser.add_argument(
    '/spec',
    dest = 'ifc_version',
    default = 'latest',
    help = 'the IFC version spec to target'
  )
  parser.add_argument(
    '/list-specs',
    dest = 'list_targets',
    action = 'store_true',
    help = 'list available spec targets and exit'
  )
  parser.add_argument(
    '/arch',
    dest = 'architecture',
    default = 'default',
    help = 'the target architecture'
  )
  parser.add_argument(
    '/manifest',
    dest = 'gen_manifest',
    action = 'store_true',
    help = 'generate a manifest of new files'
  )
  parser.add_argument(
    '/log',
    dest = 'use_log',
    action = 'store_true',
    help = 'write to "output.log" instead of stdout'
  )
  parser.add_argument(
    '/dump',
    dest = 'dump_options',
    choices = ['ifcs', 'headers'],
    help = 'dump the given config related data instead of executing a build'
  )
  parser.add_argument(
    'ifcspec_path',
    nargs = '?',
    help = 'the IFC file to build'
  )
  return parser.parse_args()

WARN_ERR_PREFIX = "IFCSPEC - "

def print_fatal_setup_error(message):
  '''Print the given error with commentary, then exit.'''
  print(f"{WARN_ERR_PREFIX}FATAL SETUP ERROR: {message}")
  sys.exit(1)

def validate_environment():
  '''Validate the environment, exit if incorrect.'''
  if 'EDG_IFC_COMPILER_DEFINITIONS' not in os.environ:
    print_fatal_setup_error(
      '"EDG_IFC_COMPILER_DEFINITIONS" should be set to the path of the json '
      'containing the compiler definitions.'
    )

def validate_argument_selection(args, compiler_targets):
  '''Validate the argument selection, exit if incorrect.'''
  if args.ifc_version not in compiler_targets:
    print_fatal_setup_error(
      f"IFC version target \"{args.ifc_version}\" was not found "
      'in the provided config'
    )

  target = compiler_targets[args.ifc_version]
  if not target.supports_architecture(args.architecture):
    print_fatal_setup_error(
      f"Architecture \"{args.architecture}\" was not found "
      'in the provided config'
    )

  if args.dump_options is not None:
    # Validate arguments when dumping information.
    if args.gen_manifest:
      print_fatal_setup_error(
        "/manifest is not compatible with /dump"
      )
  else:
    # Validate arguments when not dumping information.
    if not args.ifcspec_path.endswith('.ifcspec'):
      print_fatal_setup_error(
        f"Provided file \"{args.ifcspec_path}\" is not an \".ifcspec\" file"
      )

    if not os.path.exists(args.ifcspec_path):
      print_fatal_setup_error(
        f"ifcspec file \"{args.ifcspec_path}\" does not exist"
      )

def print_target_list(compiler_targets):
  named_compiler_targets = compiler_targets.items()

  aliases = set()
  first = True
  for target_name, compiler_target in named_compiler_targets:
    # Skip if this was determined to be an alias.
    if target_name in aliases:
      continue

    if not first:
      print('')
    first = False

    print(target_name, end = '')

    local_aliases = []
    for other_target_name, other_compiler_target in named_compiler_targets:
      if target_name == other_target_name:
        continue
      if other_compiler_target is compiler_target:
        aliases.add(other_target_name)
        local_aliases.append(other_target_name)

    if len(local_aliases) > 0:
      print(f" (aka: {', '.join(local_aliases)})", end = '')

    print('')

    architectures = compiler_target.get_supported_architectures()
    print(f"  Architectures: {', '.join(architectures)}")
    print(f"    Default: {compiler_target.default_architecture}")

def _get_dumped_path(compiler_target, architecture, dump_options):
  '''Return the path who's info to dump for the given arguments.'''
  if dump_options == 'ifcs':
    base_path = compiler_target.get_ifc_path(architecture)
    # Prefer debug files.
    possible_better_path = Path(os.path.join(base_path, 'debug'))
    if os.path.exists(possible_better_path):
      return possible_better_path
    return base_path
  if dump_options == 'headers':
    return compiler_target.get_inc_path(architecture)
  assert False

def dump_info(compiler_target, architecture, dump_options):
  '''Dump the requested information for the given arguments.

  This currently only supports dumping the file tree for a given path. All
  directories are printed first and with a trailing path separator (as this is
  a Windows script that's '\').

  The first line of output will always be the root directory, and all
  directories are printed before their files.
  '''
  dumped_path = _get_dumped_path(compiler_target, architecture, dump_options)
  for root, dirs, filenames in os.walk(dumped_path):
    print(f"{root}{os.path.sep}")
    for filename in filenames:
      print(os.path.join(root, filename))

REQUIRED_VARIABLES = {'BUILD_ARGS', 'REQUIRES_FILES'}
OPTIONAL_VARIABLES = {'MOD_OUTPUT_DIRS'}
KNOWN_VARIABLES = REQUIRED_VARIABLES.union(OPTIONAL_VARIABLES)

def _validate_ifcspec_vars(ifcspec_vars):
  '''Validate that a given ifcspec has the required variables.'''
  for required_var in REQUIRED_VARIABLES:
    if required_var not in ifcspec_vars:
      print_fatal_setup_error(
        f"Required variable {required_var} not specified in the ifcspec file"
      )

  if '/ifcOnly:edg' in ifcspec_vars['BUILD_ARGS']:
    print_warning(
      'The ifcspec file specifies "/ifcOnly:edg". This may unintentionally '
      'alter the version of the produced IFC file.'
    )

def load_ifc_vars(ifcspec_path):
  '''Load and validate the ifcspec at the given path.'''
  variables = {}
  with open(ifcspec_path, 'r') as ifcspec_file:
    line_no = 0

    for line_no, line in enumerate(ifcspec_file.readlines(), start=1):
      # Allow comments starting with "#" and empty lines.
      if line.startswith('#') or len(line.strip()) == 0:
        continue

      # If there's no match, and this wasn't a comment error.
      var_match = KEY_VALUE_REGEX.match(line)
      if var_match is None:
        print_fatal_setup_error(
          f"Invalid ifcspec file, line {line_no} was not a comment "
          'or syntactically valid variable'
        )

      # Check to make sure this variable is supported/not typoed.
      var_name = var_match[1]
      if var_name not in KNOWN_VARIABLES:
        print_fatal_setup_error(
          f"Invalid ifcspec file, line {line_no} contains an unknown variable "
          f"{var_name}"
        )

      var_value = var_match[2]
      variables[var_name] = var_value

  # Ensure this is a valid set of variables.
  _validate_ifcspec_vars(variables)

  return variables

def print_warning(message):
  '''Print a script friendly warning.

  Used to print a warning that can be automatically extracted via a calling
  script.
  '''
  print(f"{WARN_ERR_PREFIX}SPEC WARNING: {message}")

def get_current_working_files():
  '''Return a list of files in the current working directory.

  The returned file paths are returned as relative paths to the current working
  directory, and with Unix-style path separators instead of Windows path
  separators.
  '''
  cwd = os.getcwd() + os.sep

  current_files = []
  for root, dirs, filenames in os.walk(cwd):
    for filename in filenames:
      file_path = os.path.join(root, filename)
      relative_name = file_path.replace(cwd, '')
      unix_name = relative_name.replace(os.sep, '/')
      current_files.append(unix_name)

  return current_files

class IFCBuild:
  '''Represents an IFC build for a given target and architecture.'''

  def __init__(self, compiler_target, architecture):
    self.compiler_target = compiler_target
    self.architecture = architecture
    self.built_ifcspecs = set()
    self.original_working_files = get_current_working_files()

  def _get_ifcspec_dependencies(self, ifcspec_vars):
    '''Return ifcspec files depended on by the ifcspec variables.'''
    raw_required_files = ifcspec_vars['REQUIRES_FILES'].split(' ')
    return filter(lambda f: f.endswith('.ifcspec'), raw_required_files)

  def _build_dependents(self, ifcspec_path, ifcspec_vars):
    '''Build the dependencies for the given ifcspec variables.'''
    ifcspec_dependencies = self._get_ifcspec_dependencies(ifcspec_vars)
    for ifcspec_dependency in ifcspec_dependencies:
      # Skip self references so we don't build the dependent thing before its
      # dependencies.
      if ifcspec_path == ifcspec_dependency:
        continue

      # Only process dependencies once if multiple things reference the same
      # dependency.
      if ifcspec_dependency not in self.built_ifcspecs:
        self.process_ifcspec(ifcspec_dependency)

  def _make_module_output_dirs(self, ifcspec_vars):
    '''Create any module output directories for the ifcspec variables.'''
    requested_output_dirs = ifcspec_vars.get('MOD_OUTPUT_DIRS', '').split(' ')
    for requested_dir in requested_output_dirs:
      if len(requested_dir) == 0:
        continue

      os.makedirs(requested_dir, exist_ok=True)

  def _get_compiler_command(self, ifcspec_vars):
    '''Get the compiler command parts array for the ifcspec variables.

    In addition to the arguments specified by the ifcspec variables, this
    includes the compiler executable itself, and also applies command arguments
    specified by the compiler target and architecture combination.

    If any incompatible extra flags are encountered, a warning will be printed.
    '''
    compiler = self.compiler_target.get_compiler(self.architecture)
    build_args = [compiler]

    # Get the args defined by the ifcspec itself.
    ifcspec_args = shlex.split(ifcspec_vars['BUILD_ARGS'], posix=False)

    # Add any extra arguments checking for incompatibilities.
    for extra_flag in self.compiler_target.extra_flags:
      incompatibility = extra_flag.check_for_incompatibility(ifcspec_args)
      if incompatibility is not None:
        print_warning(
          f"Skipping extra flag {extra_flag.flag} due to incompatibility with "
          f"{incompatibility}"
        )
        continue

      build_args.append(extra_flag.flag)

    # Add the args from the ifcspec.
    build_args.extend(ifcspec_args)

    return build_args

  def _write_product_manifest(self, original_working_files):
    '''Write a manifest.txt file.

    This file contains all newly produced files compared to the original set of
    files, with one file per line, and is written with Unix-style line endings.
    '''
    new_files_list = []
    for current_file in get_current_working_files():
      if current_file not in original_working_files:
        new_files_list.append(current_file)

    # Write a Unix-style manifest of the new files.
    with open("product-manifest.txt", 'w', newline='\n') as manifest:
      for new_file in new_files_list:
        manifest.write(new_file)
        manifest.write('\n')

  def process_ifcspec(self, ifcspec_path, gen_manifest = False):
    '''Build an ifcspec file with optional manifest generation.

    This will build the given ifcspec file and any dependencies recursively.

    If using manifest generation, only those files produced by the original
    request will be included (files produced when processing dependencies are
    ignored). If a file already exists in the working directory, it will also
    be ignored.

    Each executed compiler's joint stdout and stderr will also be printed
    within script friendly textual labels. Along with a script friendly
    printout of the respective compiler's exit code.
    '''
    ifcspec_vars = load_ifc_vars(ifcspec_path)

    # Make sure any dependencies are loaded.
    self._build_dependents(ifcspec_path, ifcspec_vars)

    # Make sure any output directories have been created.
    self._make_module_output_dirs(ifcspec_vars)

    original_working_files = []
    if gen_manifest:
      original_working_files = get_current_working_files()

    # Create the build args.
    compiler_command_parts = self._get_compiler_command(ifcspec_vars)
    print(f"COMPILER CMD: {' '.join(compiler_command_parts)}")

    # Load the environment.
    msvs_env = self.compiler_target.get_environment(self.architecture)
    # Run the subprocess with the processed MSVS environment, and stderr and
    # stdout merged for proper sequential output.
    completed_process = subprocess.run(
      compiler_command_parts, env=msvs_env,
      stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    print("COMPILER OUTPUT BEGIN")
    print(completed_process.stdout.decode(errors = 'backslashreplace'))
    print("COMPILER OUTPUT END")
    print(f"COMPILER EXIT CODE: {completed_process.returncode}")

    self.built_ifcspecs.add(ifcspec_path)

    # A manifest was requested (presumably for a remote build)
    if gen_manifest:
      self._write_product_manifest(original_working_files)

def _execute_arguments(args):
  '''Internal function to execute the script for the given arguments.

  This is effectively the true "main" function but is extracted to allow the
  same logic to be used with and without stdout optionally being redirected to
  a log.
  '''
  # Make sure the environment is at a bare minimum state for us to continue.
  validate_environment()

  # Load the compiler targets from the configuration file.
  compiler_targets = load_compiler_targets()

  # If we've been asked to list targets, do that now and exit.
  # FIXME: This should ideally go through argument validation, but that
  # code needs updated.
  if args.list_targets:
    print_target_list(compiler_targets)
    sys.exit(0)

  # Validate that the combination of the arguments and loaded compiler targets
  # leads to something valid.
  validate_argument_selection(args, compiler_targets)

  # Resolve the specific compiler target.
  compiler_target = compiler_targets[args.ifc_version]

  # If we're executing a target specific dump, do that now and exit.
  if args.dump_options is not None:
    # Dump the requested information.
    dump_info(compiler_target, args.architecture, args.dump_options)
    sys.exit(0)

  # Build the given ifcspec for the selected architecture.
  ifc_build = IFCBuild(compiler_target, args.architecture)
  ifc_build.process_ifcspec(args.ifcspec_path, args.gen_manifest)

def main() -> None:
  args = parse_args()

  # If the user requested the use of a log file instead of stdout, send stdout
  # to "output.log" using Unix-style line endings, otherwise use stdout as
  # normal.
  if args.use_log:
    with open('output.log', 'w', newline='\n') as build_log:
      with redirect_stdout(build_log):
        _execute_arguments(args)
  else:
    _execute_arguments(args)

main()
