#!/usr/bin/env bash

# Change working directory to where the script is located
DIR=$(dirname ${0})
cd ${DIR}


if [ ! -d vmware-python ]; then
	python3.7 -m venv vmware-python
	source vmware-python/bin/activate
	pip install --upgrade pip
	pip install --upgrade setuptools
	pip install --upgrade pyvmomi
	pip install --upgrade pyyaml
	pip install ipython
fi
