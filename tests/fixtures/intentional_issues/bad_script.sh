#!/bin/bash
# Shell script with shellcheck issues

name="World"
echo "Hello $name"

# SC2002: useless cat
cat some_file | grep "pattern"

# SC2086: double quote to prevent globbing and word splitting
if [ -f $HOME/.config ]
then
    echo "config exists"
fi

# SC2046: quote to prevent word splitting
ls -la `find . -name "*.txt"`
