# Copyright (C) 2015 Oleh Prypin <blaxpirit@gmail.com>
# 
# This file is part of nim-csfml.
# 
# This software is provided 'as-is', without any express or implied
# warranty. In no event will the authors be held liable for any damages
# arising from the use of this software.
# 
# Permission is granted to anyone to use this software for any purpose,
# including commercial applications, and to alter it and redistribute it
# freely, subject to the following restrictions:
# 
# 1. The origin of this software must not be misrepresented; you must not
#    claim that you wrote the original software. If you use this software
#    in a product, an acknowledgement in the product documentation would be
#    appreciated but is not required.
# 2. Altered source versions must be plainly marked as such, and must not be
#    misrepresented as being the original software.
# 3. This notice may not be removed or altered from any source distribution.


import sys
import re
import textwrap
import itertools

from pycparser import parse_file, c_ast, c_generator



with open('docs_gen.txt') as f:
    docs = f.read().strip().split('\n--------\n')


def rename_sf(name):
    if name is None:
        return name
    # Workaround for not having https://github.com/SFML/CSFML/pull/130 in CSFML tag 2.5
    if name == "getLineSpacing":
        return 'Text_getLineSpacing'
    if not name.startswith('sf'):
        raise ValueError(name)
    return name[2:]

def rename_type(name, var=''):
    orname = name
    m = re.match('^(.+) *\[([0-9\* ]+)\]$', name)
    if m:
        name, arrsize = m.groups()
    else:
        arrsize = None
    name = re.sub(r'\bconst\b', '', name).strip()
    if name.startswith('sf') and ('Int' in name or 'Uint' in name) and 'Rect' not in name:
        name = name[2:].lower()
    ptr = len(name)
    name = name.rstrip('*')
    ptr -= len(name)
    name = name.strip()
    name = {
        'int': 'cint',
        'size_t': 'int',
        'unsigned int': 'cint',
        'float': 'cfloat',
        'sfBool': 'BoolInt',
        'sfVector2u': 'sfVector2i',
    }.get(name, name)
    if ptr and name=='void':
        ptr -= 1
        name = 'pointer'
    if ptr and 'sf' in name:
        if rename_sf(name) in classes:
            ptr -= 1
        if rename_sf(name) not in classes and not (var.endswith('s') and var[-2:]!=name[-2:]):
            ptr -= 1
            name = 'var {}'.format(rename_sf(name))
    try:
        name = rename_sf(name)
    except ValueError:
        pass
    name = 'ptr '*ptr+name
    if name=='ptr char':
        name = 'cstring'
    if arrsize:
        name = 'array[{}, {}]'.format(arrsize, name)
    return name

def rename_identifier(name):
    name = {
        'object': 'obj',
        'type': 'kind',
        'bind': 'bindGL',
    }.get(name, name)
    name = name.replace('String', 'Str').replace('string', 'str')
    return name[0].lower()+name[1:]

def common_start(strings):
    if not strings:
        return ''
    first = strings[0]
    for i in range(1, len(first)+1):
        if not all(s[:i]==first[:i] for s in strings):
            return first[:i-1]
    return first


def get_doc(indent=2):
    global doc
    if doc is None:
        return None
    r = '\n'.join(indent*' '+'## '+l for l in doc.splitlines())
    doc = None
    return r


def handle_enum(name, items):
    if name is None:
        yield 'const'
        for name, value in items:
            name = rename_sf(name)
            yield ('  {}* = {}'.format(name, value) if value is not None else name)
        return
    
    nitems = [name for name, value in items]
    c = len(common_start(nitems))
    nitems = [nitem[c:] for nitem in nitems]
    nitems = list(zip(nitems, (value for name, value in items)))

    nname = rename_sf(name)
    if all(value is not None for name, value in nitems):
        nitems.sort(key=lambda kv: int(kv[1]))
    r = 'type {}* {{.pure, size: sizeof(cint).}} = enum'.format(nname)
    d = get_doc()
    if d: r += d
    yield r
    yield '\n'.join(textwrap.wrap(', '.join(
        '{} = {}'.format(name, value) if value is not None else name
        for name, value in nitems if not str(value).startswith('sf')
    ), 80, initial_indent='  ', subsequent_indent='  '))

def handle_struct(name, items):
    if name=='sfVector2u':
        return
    name = rename_type(name)
    yield 'type {}* {{.bycopy.}} = object'.format(name)
    d = get_doc()
    if d: yield d

    for typ, name in items:
        if typ in ['sfEventType']:
            continue
        typ = rename_type(typ)
        if typ=='uint32' and name=='unicode':
            typ = 'RuneU32'
        elif typ=='uint32' and name=='attributeFlags':
            typ = 'BitMaskU32'
        yield '  {}*: {}'.format(name, typ)


classes = set()
def handle_class(name):
    pname = rename_sf(name)
    classes.add(pname)
    yield 'type {0}* = ptr object'.format(pname)
    d = get_doc()
    if d: yield d


def handle_function(main, params):
    public = '*'
    ftype, fname = main
    nfname = rename_sf(fname)
    nfname = re.sub(r'(.+)_create.*', r'new\1', nfname)
    nfname = re.sub(r'(.+)_from.+', r'\1', nfname)
    nfname = re.sub(r'(.+)With.+', r'\1', nfname)
    nfname = re.sub(r'([gs]et.+)RenderWindow$', r'\1', nfname)
    if nfname != 'Shader_setCurrentTextureParameter':
        nfname = re.sub(r'_set(.+)Parameter$', r'_setParameter', nfname)
    if 'unicode' in fname.lower():
        nfname += '_U32'
    if params:
        p1 = rename_type(params[0][0])+'_'
        if p1.startswith('var '):
            p1 = p1[4:]
        if nfname.startswith(p1):
            nfname = nfname[len(p1):]
    nfname = rename_identifier(nfname)
    nftype = rename_type(ftype).replace('var ', 'ptr ')
    main_sgn = 'proc {nfname}{public}({sparams}): {nftype}'
    main_fn = '{nfname}'
    pragmas = []
    if nfname.startswith('get') and nfname[3].isupper() and len(params)==1:
        nfname = nfname[3].lower()+nfname[4:]
    elif nfname.startswith('is') and nfname[2].isupper() and len(params)==1:
        nfname = nfname[2].lower()+nfname[3:]
    elif nfname.startswith('set') and nfname[3].isupper() and len(params)==2:
        main_sgn = 'proc `{nfname}=`{public}({sparams}): {nftype}'
        main_fn = '`{nfname}=`'
        nfname = nfname[3].lower()+nfname[4:]
    if nfname.startswith('unicode'):
        nfname = nfname[7].lower()+nfname[8:]
    if nftype=='void':
        main_sgn = main_sgn[:-10]
    if nftype=='cstring' and nfname in ['str', 'title']:
        nfname += 'C'
    if nftype=='ptr uint32':
        nftype = 'StringU32'
        public = ''
    if nftype=='uint32':
        if nfname in ['style']: nftype = 'BitMaskU32'
        else:
            if 'Font' in fname: nftype = 'RuneU32'
    #if nftype.startswith('ptr ') or nftype=='pointer':
        #public = ''
    r = []
    for repl in itertools.product((False, True), repeat=len(params)):
        aparams = []
        replv = []
        sgn = main_sgn
        for i, (repl, (ptype, pname)) in enumerate(zip(repl, params), 1):
            rtype = rename_type(ptype, pname)
            rname = rename_identifier(pname) or 'p{}'.format(i)
            if rtype=='cstring' and rname in ['str', 'title']:
                if not nfname.endswith('C'):
                    nfname += 'C'
            if rtype=='ptr uint32':
                rtype = 'StringU32'
                public = ''
            if rtype=='uint32':
                if rname in ['style']: rtype = 'BitMaskU32'
                else:
                    if 'Font' in fname: rtype = 'RuneU32'
            if ptype.startswith('const') and rtype.startswith('var '):
                if repl:
                    rrtype = rtype[4:]
                    replv.append(rname)
                else:
                    rrtype = '({}){{lvalue}}'.format(rtype)
            else:
                rrtype = rtype
            #if rtype.startswith('ptr ') or rtype=='pointer':
                #public = ''
            aparams.append((rname, rrtype))
        sparams = ', '.join('{}: {}'.format(*p) for p in aparams)
        if replv:
            pr = ' {{.\n  {}.}}'.format(', '.join(pragmas)) if pragmas else ''
            s = sgn.format(**locals())+pr+' ='
            s += '\n  ('+'; '.join('var C{0} = {0}'.format(rname) for rname in replv)
            s += ')\n  '
            s += main_fn.format(**locals())
            s += '('+', '.join('C'+p if p in replv else p for p, _ in aparams)+')'
            if s not in r:
                r.append(s)
        else:
            pr = pragmas+['cdecl', 'importc: "{}"'.format(fname)]
            pr = ' {{.\n  {}.}}'.format(', '.join(pr))
            s = sgn.format(**locals())+pr
            if s not in r:
                r.append(s)
    d = get_doc()
    if d:
        if r[-1].count('\n')<=1:
            r[-1] += '\n'+d
        else:
            r[-1] = '\n'.join(r[-1].splitlines()[0:1]+[d]+r[-1].splitlines()[1:])
    yield '\n'.join(r)


def handle_functiondef(main, params):
    ftype, fname = main
    params = '; '.join(
        '{}: {}'.format(pname or 'p{}'.format(i), rename_type(ptype)) 
        for i, (ptype, pname) in enumerate(params, 1)
    )
    yield 'type {}* = proc({}): {} {{.cdecl.}}'.format(rename_sf(fname), params, rename_type(ftype))


cgen = c_generator.CGenerator()

def type_to_str(node):
    ptrs = 0
    while isinstance(node, c_ast.PtrDecl):
        node = node.type
        ptrs += 1
    return ' '.join(node.type.names)+'*'*ptrs, node.declname

def gen_expr_to_str(node):
    return cgen.visit(node)

def gen_type_to_str(node):
    name = None
    try: name = node.name
    except AttributeError: pass
    try: name = node.declname
    except AttributeError: pass
    typ = gen_expr_to_str(node)
    if name:
        typ = ' '.join(re.sub(r'\b{}\b'.format(name), '', typ).split())
    return typ, name


def _debug(node):
    try:
        for k, v in node.__dict__.items():
            if k.startswith('_'):
                continue
            if isinstance(v, list) and len(v)>0:
                yield '{} = ['.format(k)
                for it in v:
                    yield '    {!r} ('.format(it)
                    for l in _debug(it):
                        yield textwrap.indent(l, '        ')
                    yield ')'
                yield ']'
            else:
                yield '{} = {!r} ('.format(k, v)
                for l in _debug(v):
                    yield textwrap.indent(l, '    ')
                yield ')'
    except Exception as e:
        pass
def debug(node):
    class root:
        pass
    root = root()
    root.root = node
    r = '\n'.join(_debug(root))[7:]
    r = re.sub(r' \(\n *\)', '', r)
    r = re.sub(r' object at 0x[0-9a-f]+', '', r)
    return r

class Visitor(c_ast.NodeVisitor):
    def __init__(self):
        super().__init__()
        self.names = {}

    def visit_FuncDecl(self, node):
        try:
            func_type, func_name = type_to_str(node.type)
            func_params = [gen_type_to_str(param_decl) for param_decl in node.args.params] if node.args else []
            if len(func_params)==1 and func_params[0][0]=='void':
                func_params = []
            out(*handle_function((func_type, func_name), func_params))
        except AttributeError as e:
            print(func_name, repr(e), file=sys.stderr)

    def visit_Typedef(self, node):
        if isinstance(node.type.type, c_ast.IdentifierType):
            try:
                out('type {}* = {}'.format(rename_sf(node.name), rename_sf(' '.join(node.type.type.names))))
            except (NameError, ValueError):
                pass
            return
        if isinstance(node.type.type, (c_ast.Enum, c_ast.Struct)):
            self.names[node.type.type] = node.type.declname
        if type(node.type.type).__name__=='Union':
            out('include union_{}'.format(rename_sf(node.type.declname).lower()))
        try:
            r = (
                (gen_type_to_str(node.type.type.type.type)[0], node.name),
                [gen_type_to_str(p) for p in node.type.type.args.params]
            )
        except Exception as e:
            pass
        else:
            out(*handle_functiondef(*r))
            return

        self.generic_visit(node)

    def visit_Enum(self, node):
        name = self.names.get(node, node.name)
        if node.values:
            items = [
                (en.name, (gen_expr_to_str(en.value) if en.value else None))
                for en in node.values.enumerators
            ]
            out(*handle_enum(name, items))
        else:
            if name.startswith('doc'):
                global doc
                doc = docs[int(name[3:])-1].strip()
                doc = re.sub(r'(Example:\s+)?\\code(.|\n)+?\\endcode\n', r'', doc)
                doc = re.sub(r'\\brief ', r'', doc)
                doc = re.sub(r'\\param', r'*Arguments*:\n\\param', doc, 1)
                doc = re.sub(r'\\param ([a-zA-Z0-9_]+)', r'- ``\1``: ', doc)
                doc = re.sub(r'\\li ', r'- ', doc)
                doc = re.sub(r'\\a ([a-zA-Z0-9_]+)', r'``\1``', doc)
                doc = re.sub(r'\\return ', r'*Returns:* ', doc)
                doc = re.sub(r'\bsf([A-Z])', r'\1', doc)
            else:
                global cmodule
                cmodule = name.split('_')[1].lower()
                out('\n#--- {} ---#'.format(name.replace('_', '/')))

        self.generic_visit(node)

    def visit_Struct(self, node):
        name = self.names.get(node, node.name)
        if node.decls:
            items = [gen_type_to_str(decl) for decl in node.decls]
            out(*handle_struct(name, items))
        else:
            out(*handle_class(name))

        self.generic_visit(node)



files = {}
def out(*args):
    if not args:
        return
    try:
        f = files[cmodule]
    except KeyError:
        files[cmodule] = f = open('{}_gen.nim'.format(cmodule), 'w')
    else:
        if not args[0].startswith(' '):
            print(file=f)
    for arg in args:
        print(arg, file=f)


ast = parse_file('headers_gen.h')
Visitor().visit(ast)
