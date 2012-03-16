#!/usr/bin/env python
##########################################################################
#
# Copyright 2011 Jose Fonseca
# All Rights Reserved.
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
##########################################################################/


import difflib
import optparse
import os.path
import subprocess
import sys

from unpickle import Unpickler
from highlight import ColorHighlighter, LessHighlighter


ignoredFunctionNames = set([
    'glGetString',
    'glXGetClientString',
    'glXGetCurrentDisplay',
    'glXGetProcAddress',
    'glXGetProcAddressARB',
    'wglGetProcAddress',
])


class Loader(Unpickler):

    def __init__(self, stream):
        Unpickler.__init__(self, stream)
        self.calls = []

    def handleCall(self, call):
        if call.functionName not in ignoredFunctionNames:
            self.calls.append(call)
            hash(call)


def readtrace(trace, calls):
    p = subprocess.Popen(
        args = [
            options.apitrace,
            'pickle',
            '--symbolic',
            '--calls=' + calls,
            trace
        ],
        stdout = subprocess.PIPE,
    )

    calls = []
    parser = Loader(p.stdout)
    parser.parse()
    return parser.calls


class SDiffer:

    def __init__(self, a, b, highlighter, callNos = False):
        self.a = a
        self.b = b
        self.highlighter = highlighter
        self.delete_color = highlighter.red
        self.insert_color = highlighter.green
        self.callNos = callNos

    def diff(self):
        matcher = difflib.SequenceMatcher(self.isjunk, self.a, self.b)
        for tag, alo, ahi, blo, bhi in matcher.get_opcodes():
            if tag == 'replace':
                self.replace(alo, ahi, blo, bhi)
            elif tag == 'delete':
                self.delete(alo, ahi)
            elif tag == 'insert':
                self.insert(blo, bhi)
            elif tag == 'equal':
                self.equal(alo, ahi, blo, bhi)
            else:
                raise ValueError, 'unknown tag %s' % (tag,)

    def isjunk(self, call):
        return call.functionName == 'glGetError' and call.ret in ('GL_NO_ERROR', 0)

    def replace(self, alo, ahi, blo, bhi):
        assert alo < ahi and blo < bhi
        
        a_names = [call.functionName for call in self.a[alo:ahi]]
        b_names = [call.functionName for call in self.b[blo:bhi]]

        matcher = difflib.SequenceMatcher(None, a_names, b_names)
        for tag, _alo, _ahi, _blo, _bhi in matcher.get_opcodes():
            _alo += alo
            _ahi += alo
            _blo += blo
            _bhi += blo
            if tag == 'replace':
                self.replace_dissimilar(_alo, _ahi, _blo, _bhi)
            elif tag == 'delete':
                self.delete(_alo, _ahi)
            elif tag == 'insert':
                self.insert(_blo, _bhi)
            elif tag == 'equal':
                self.replace_similar(_alo, _ahi, _blo, _bhi)
            else:
                raise ValueError, 'unknown tag %s' % (tag,)

    def replace_similar(self, alo, ahi, blo, bhi, prefix = None):
        assert alo < ahi and blo < bhi
        assert ahi - alo == bhi - blo
        if prefix is None:
            prefix = self.replace_prefix
        for i in xrange(0, bhi - blo):
            a_call = self.a[alo + i]
            b_call = self.b[blo + i]
            assert a_call.functionName == b_call.functionName
            assert len(a_call.args) == len(b_call.args)
            prefix()
            if self.callNos:
                self.replace_value(a_call.no, b_call.no)
                self.highlighter.write(' ')
            self.highlighter.bold(True)
            self.highlighter.write(b_call.functionName)
            self.highlighter.bold(False)
            self.highlighter.write('(')
            sep = ''
            for j in xrange(len(b_call.args)):
                self.highlighter.write(sep)
                self.replace_value(a_call.args[j], b_call.args[j])
                sep = ', '
            self.highlighter.write(')')
            if a_call.ret is not None or b_call.ret is not None:
                self.highlighter.write(' = ')
                self.replace_value(a_call.ret, b_call.ret)
            self.highlighter.write('\n')

    def replace_dissimilar(self, alo, ahi, blo, bhi):
        assert alo < ahi and blo < bhi
        if bhi - blo < ahi - alo:
            first  = self.insert(blo, bhi)
            second = self.delete(alo, ahi)
        else:
            first  = self.delete(alo, ahi)
            second = self.insert(blo, bhi)

        for g in first, second:
            for line in g:
                yield line

    def replace_value(self, a, b):
        if b == a:
            self.highlighter.write(str(b))
        else:
            self.highlighter.strike()
            self.highlighter.color(self.delete_color)
            self.highlighter.write(str(a))
            self.highlighter.normal()
            #self.highlighter.write(" -> ")
            self.highlighter.write(" ")
            self.highlighter.color(self.insert_color)
            self.highlighter.write(str(b))
            self.highlighter.normal()

    escape = "\33["

    def delete(self, alo, ahi):
        self.dump(self.delete_prefix, self.a, alo, ahi, self.normal_suffix)

    def insert(self, blo, bhi):
        self.dump(self.insert_prefix, self.b, blo, bhi, self.normal_suffix)

    def equal(self, alo, ahi, blo, bhi):
        if self.callNos:
            self.replace_similar(alo, ahi, blo, bhi, prefix=self.equal_prefix)
        else:
            self.dump(self.equal_prefix, self.b, blo, bhi, self.normal_suffix)

    def dump(self, prefix, x, lo, hi, suffix):
        for i in xrange(lo, hi):
            call = x[i]
            prefix()
            if self.callNos:
                self.highlighter.write(str(call.no) + ' ')
            self.highlighter.bold(True)
            self.highlighter.write(call.functionName)
            self.highlighter.bold(False)
            self.highlighter.write('(' + ', '.join(map(repr, call.args)) + ')')
            if call.ret is not None:
                self.highlighter.write(' = ' + repr(call.ret))
            suffix()
            self.highlighter.write('\n')

    def delete_prefix(self):
        self.highlighter.write('- ')
        self.highlighter.strike()
        self.highlighter.color(self.delete_color)
    
    def insert_prefix(self):
        self.highlighter.write('+ ')
        self.highlighter.color(self.insert_color)

    def equal_prefix(self):
        self.highlighter.write('  ')

    def normal_suffix(self):
        self.highlighter.normal()
    
    def replace_prefix(self):
        self.highlighter.write('| ')


def main():
    '''Main program.
    '''

    # Parse command line options
    optparser = optparse.OptionParser(
        usage='\n\t%prog <trace> <trace>',
        version='%%prog')
    optparser.add_option(
        '-a', '--apitrace', metavar='PROGRAM',
        type='string', dest='apitrace', default='apitrace',
        help='apitrace command [default: %default]')
    optparser.add_option(
        '-c', '--calls', metavar='CALLSET',
        type="string", dest="calls", default='1-10000',
        help="calls to compare [default: %default]")
    optparser.add_option(
        '--ref-calls', metavar='CALLSET',
        type="string", dest="ref_calls", default=None,
        help="calls to compare from reference trace")
    optparser.add_option(
        '--src-calls', metavar='CALLSET',
        type="string", dest="src_calls", default=None,
        help="calls to compare from source trace")
    optparser.add_option(
        '--call-nos',
        action="store_true",
        dest="call_nos", default=False,
        help="dump call numbers")
    global options
    (options, args) = optparser.parse_args(sys.argv[1:])
    if len(args) != 2:
        optparser.error("incorrect number of arguments")

    if options.ref_calls is None:
        options.ref_calls = options.calls
    if options.src_calls is None:
        options.src_calls = options.calls

    ref_calls = readtrace(args[0], options.ref_calls)
    src_calls = readtrace(args[1], options.src_calls)

    if sys.stdout.isatty():
        highlighter = LessHighlighter()
    else:
        highlighter = ColorHighlighter()

    differ = SDiffer(ref_calls, src_calls, highlighter, options.call_nos)
    differ.diff()


if __name__ == '__main__':
    main()
