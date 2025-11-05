#!/usr/bin/env bash
#===============================================================================
# Script Name   : build.sh
# Description   : Builds the Docker image for the ShiftrX challenge using the
#                 specified Dockerfile and tags it as 'latest'.
# Usage         : scripts/build_docker_image.sh
#===============================================================================

docker build -f docker/Dockerfile -t davidparks21/shiftrx_challenge:latest .
