# Rem IFC

This project contains scripts EDG used to develop the front end for the
Microsoft IFC variant.

The Rem IFC service was a service for interfacing with a remote Windows
machine over SSH to create and download an IFC file (as produced by MSVC).

There are two primary components the CLI scripts usable from Unix-like systems
in bin as well as scripts intended to run on the Windows host in
services/RemIFC.  RemIFC/build-ifc.py could also be used without the CLI
scripts to build IFC files using MSVC using the "IFCSpec" as a recipe.

These scripts are not of sufficient quality to be included in the Open Source
release without additional refinement to generalize them from EDG
infrastructure.
