#!/usr/bin/bash

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

standard_type_checks=()
strict_type_checks=()

function check_types {
  standard_type_checks+=("$(realpath $1)")
}

function check_types_strict {
  strict_type_checks+=("$(realpath $1)")
}

pushd bin/ > /dev/null
  check_types get-ifcspec-dependencies
  check_types rem-build-ifcspecs
  check_types rem-build-ifc-check
popd > /dev/null

pushd services/RemIFC/ > /dev/null
  pushd RemIFC/ > /dev/null
    check_types build-ifc.py
  popd > /dev/null
popd > /dev/null

echo 'Running checks...'
mypy --no-namespace-packages \
     --scripts-are-modules   \
     --strict-equality       \
     "${standard_type_checks[@]}"

echo 'Running strict checks...'
mypy --no-namespace-packages  \
     --scripts-are-modules    \
     --strict-equality        \
     --disallow-untyped-defs  \
     --disallow-untyped-calls \
     "${strict_type_checks[@]}"
