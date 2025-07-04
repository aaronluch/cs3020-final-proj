from typing import Set, Dict, Optional
import itertools
import sys
import traceback

from cs3020_support.python import *
import cs3020_support.x86 as x86
import constants
import cif
from interference_graph import InterferenceGraph
import print_x86defs

comparisons = ['eq', 'gt', 'gte', 'lt', 'lte']
gensym_num = 0
global_logging = False

tuple_var_types = {}

dataclass_var_types = {}
function_names = set()
function_params: Dict[str, List[str]] = {}
function_return_types = {}

_homes: Dict[str, Dict[x86.Var, x86.Arg]] = {}
debug_sets = True


def log(label, value):
    if global_logging:
        print()
        print(f'--------------------------------------------------')
        print(f'Logging: {label}')
        print(value)
        print(f'--------------------------------------------------')


def log_ast(label, value):
    log(label, print_ast(value))


def gensym(x):
    """
    Constructs a new variable name guaranteed to be unique.
    :param x: A "base" variable name (e.g. "x")
    :return: A unique variable name (e.g. "x_1")
    """

    global gensym_num
    gensym_num = gensym_num + 1
    return f'{x}_{gensym_num}'


##################################################
# typecheck
##################################################
# op     ::= "add" | "sub" | "mult" | "not" | "or" | "and" | "eq" | "gt" | "gte" | "lt" | "lte"
#          | "tuple" | "subscript"
# Expr   ::= Var(x) | Constant(n) | Prim(op, List[Expr]) | Begin(Stmts, Expr)
#          | Call(Expr, List[Expr])
# Stmt   ::= Assign(x, Expr) | Print(Expr) | If(Expr, Stmts, Stmts) | While(Expr, Stmts)
#          | Return(Expr) | FunctionDef(str, List[Tuple[str, type]], List[Stmt], type)
# Stmts  ::= List[Stmt]
# LFun   ::= Program(Stmts)

TEnv = Dict[str, type]

@dataclass
class Callable:
    args: List[type]
    output_type: type
    
@dataclass
class DataclassType:
    name: str
    fields: Dict[str, type]

def typecheck(program: Program) -> Program:
    """
    Typechecks the input program; throws an error if the program is not well-typed.
    :param program: The Lfun program to typecheck
    :return: The program, if it is well-typed
    """
    has_classes = any(isinstance(s, ClassDef) for s in program.stmts) # check if there are any classes
    prim_arg_types = {
        'add':   [int, int],
        'sub':   [int, int],
        'mult':  [int, int],
        'not': [bool],
        'or':  [bool, bool],
        'and':  [bool, bool],
        'gt':   [int, int],
        'gte':  [int, int],
        'lt':   [int, int],
        'lte':  [int, int],
    }

    prim_output_types = {
        'add':   int,
        'sub':   int,
        'mult':  int,
        'not': bool,
        'or':  bool,
        'and':  bool,
        'gt':   bool,
        'gte':  bool,
        'lt':   bool,
        'lte':  bool,
    }

    def tc_exp(e: Expr, env: TEnv) -> type:
        match e:     
            case FieldRef(o, field):
                # first, typecheck the object expression
                t_obj = tc_exp(o, env)

                if isinstance(o, Var) and o.name in dataclass_var_types:
                    t_obj = dataclass_var_types[o.name]
                else:
                    return t_obj

                # if it's still a DataclassType (first pass), just use it
                if isinstance(t_obj, DataclassType):
                    if field not in t_obj.fields:
                        raise TypeError(f"field {field!r} not in dataclass {t_obj.name}")
                    return t_obj.fields[field]

                # if it's a raw tuple (second pass), recover the original DataclassType
                if isinstance(t_obj, tuple):
                    dt = dataclass_var_types[o.name]
                    return dt.fields[field]

                # otherwise it really is an error
                raise TypeError(f"Expected DataclassType or tuple for {o}, but got {t_obj}")
                   
            case Call(func, args):
                arg_types = [tc_exp(a, env) for a in args]
                if isinstance(func, Var) and func.name in dataclass_var_types:
                    dt = dataclass_var_types[func.name]
                    n = len(arg_types)
                    
                    if not (n == 0 or n == len(dt.fields)):
                        raise TypeError(f'Expected {len(dt.fields)} arguments, but got {n}')
                    if n == len(dt.fields):
                        expected = list(dt.fields.values())
                        for actual, exp in zip(arg_types, expected):
                            assert actual == exp
                        return dt
                    
                    # normal function call
                    fn_type = tc_exp(func, env)
                    assert isinstance(fn_type, Callable)
                    assert fn_type.args == arg_types
                    return fn_type.output_type
                
            case Var(x):
                return env[x]
            case Constant(i):
                if isinstance(i, bool):
                    return bool
                elif isinstance(i, int):
                    return int
                else:
                    raise Exception('tc_exp', e)
            case Prim('eq', [e1, e2]):
                assert tc_exp(e1, env) == tc_exp(e2, env)
                return bool
            case Begin(stmts, e1):
                tc_stmts(stmts, env)
                return tc_exp(e1, env)
            case Prim('tuple', args):
                arg_types = [tc_exp(a, env) for a in args]
                t = tuple(arg_types)
                return t
            case Prim('subscript', [e1, Constant(i)]):
                t = tc_exp(e1, env)
                # handle both tuple types and DataclassType
                if isinstance(t, tuple):
                    return t[i]
                elif isinstance(t, DataclassType):
                    # if it's a dataclass type, get the field at the given index
                    field_name = list(t.fields.keys())[i]
                    return t.fields[field_name]
                else:
                    raise TypeError(f"Expected tuple or DataclassType for subscript, but got {t}")
            case Prim(op, args):
                arg_types = [tc_exp(a, env) for a in args]
                assert arg_types == prim_arg_types[op]
                return prim_output_types[op]
            case _:
                raise Exception('tc_exp', e)

    def tc_stmt(s: Stmt, env: TEnv):
        match s:
            case ClassDef(name, _superclass, body):
                # add mapping from class name to a `Callable` WHICH WILL
                # return the relevant `DataclassType` to the type env
                field_map = {fname: ftype for fname, ftype in body}
                dt = DataclassType(name, field_map)
                dataclass_var_types[name] = dt
                param_types = [ftype for _, ftype in body]
                env[name] = Callable(param_types, dt)
                    
            
            case FunctionDef(name, params, body_stmts, return_type):
                function_names.add(name)
                function_params[name] = []

                # register the function signature
                real_arg_types = []
                for pname, ptype in params:
                    if isinstance(ptype, str) and ptype in dataclass_var_types:
                        real_arg_types.append(dataclass_var_types[ptype])
                    else:
                        real_arg_types.append(ptype)
                
                if isinstance(return_type, str) and return_type in dataclass_var_types:
                    dt = dataclass_var_types[return_type]
                    real_ret = dt if has_classes else tuple(dt.fields.values())
                    function_return_types[name] = dt
                else:
                    # just add type to the return types if it's not a dataclass
                    function_return_types[name] = return_type
                    real_ret = return_type
                    
                env[name] = Callable(real_arg_types, real_ret)

                # make a fresh env for the body
                new_env = env.copy()
                for pname, ptype in params:
                    function_params[name].append(pname)
                    if has_classes:
                        # Pass 1: if the annotation is a dataclass name,
                        #   1) record the param name in dataclass_var_types
                        #   2) bind that name in the env to the DataclassType
                        if isinstance(ptype, str) and ptype in dataclass_var_types:
                            dt = dataclass_var_types[ptype]
                            new_env[pname] = dt
                            dataclass_var_types[pname] = dt
                        else:
                            new_env[pname] = ptype if not (has_classes) else ptype

                    if not has_classes:
                        # Pass 2: if we have a dataclass‐typed param,
                        #   rebind it to the tuple of its field types
                        if isinstance(ptype, str) and ptype in dataclass_var_types:
                            dt = dataclass_var_types[ptype]
                            new_env[pname] = tuple(dt.fields.values())
                        else:
                            new_env[pname] = ptype

                new_env['return value'] = real_ret
                tc_stmts(body_stmts, new_env)

            case Return(e):
                expected_type = env['return value']
                actual_type = tc_exp(e, env)
                assert env['return value'] == tc_exp(e, env), f'Expected {expected_type}, but got {actual_type}'

            case While(condition, body_stmts):
                assert tc_exp(condition, env) == bool
                tc_stmts(body_stmts, env)
            case If(condition, then_stmts, else_stmts):
                assert tc_exp(condition, env) == bool
                tc_stmts(then_stmts, env)
                tc_stmts(else_stmts, env)
            case Print(e):
                tc_exp(e, env)
                
            case Assign(x, e):
                t_e = tc_exp(e, env)
                if isinstance(t_e, DataclassType):
                    env[x] = t_e
                    dataclass_var_types[x] = t_e
                    return
                if isinstance(e, Call) and isinstance(e.function, Var) and e.function.name in function_names:
                    func_name = e.function.name
                    if func_name in function_return_types:
                        dataclass_var_types[x] = function_return_types[func_name]
                        env[x] = function_return_types[func_name]
                        return
                if isinstance(t_e, tuple):
                    tuple_var_types[x] = t_e
                    env[x] = t_e
                    return
                if x in env:
                    assert t_e == env[x]
                else:
                    env[x] = t_e
                    
            case _:
                raise Exception('tc_stmt', s)

    def tc_stmts(stmts: List[Stmt], env: TEnv):
        for s in stmts:
            tc_stmt(s, env)

    match program:
        case Program(stmts):
            env = {}
            tc_stmts(stmts, env)

            # record any new tuples or dataclasses
            for x, t in list(env.items()):
                if isinstance(t, tuple):
                    tuple_var_types[x] = t
                elif isinstance(t, DataclassType):
                    dataclass_var_types[x] = t
            return program


##################################################
# remove-complex-opera*
##################################################
# op     ::= "add" | "sub" | "mult" | "not" | "or" | "and" | "eq" | "gt" | "gte" | "lt" | "lte"
#          | "tuple" | "subscript"
# Expr   ::= Var(x) | Constant(n) | Prim(op, List[Expr])
#          | Call(Expr, List[Expr])
# Stmt   ::= Assign(x, Expr) | Print(Expr) | If(Expr, Stmts, Stmts) | While(Expr, Stmts)
#          | Return(Expr) | FunctionDef(str, List[Tuple[str, type]], List[Stmt], type)
# Stmts  ::= List[Stmt]
# LFun   ::= Program(Stmts)

def rco(prog: Program) -> Program:
    """
    Removes complex operands. After this pass, the arguments to operators (unary and binary
    operators, and function calls like "print") will be atomic.
    :param prog: An Lfun program
    :return: An Lfun program with atomic operator arguments.
    """

    def rco_stmt(stmt: Stmt, new_stmts: List[Stmt]) -> Stmt:
        match stmt:
            case FieldRef(o, field):
                return FieldRef(rco_exp(o, new_stmts), field)
            case ClassDef(name, superclass, field):
                return stmt
            case FunctionDef(name, params, body_stmts, return_type):
                return FunctionDef(name, params, rco_stmts(body_stmts), return_type)
            case Return(e):
                return Return(rco_exp(e, new_stmts))
            case Assign(x, e1):
                new_e1 = rco_exp(e1, new_stmts)
                return Assign(x, new_e1)
            case Print(e1):
                new_e1 = rco_exp(e1, new_stmts)
                return Print(new_e1)
            case If(condition, then_stmts, else_stmts):
                new_condition = rco_exp(condition, new_stmts)
                new_then_stmts = rco_stmts(then_stmts)
                new_else_stmts = rco_stmts(else_stmts)

                return If(new_condition,
                          new_then_stmts,
                          new_else_stmts)
            case While(condition, body_stmts):
                condition_stmts = []
                condition_exp = rco_exp(condition, condition_stmts)
                new_condition = Begin(condition_stmts, condition_exp)
                new_body_stmts = rco_stmts(body_stmts)
                return While(new_condition, new_body_stmts)
            case _:
                raise Exception('rco_stmt', stmt)

    def rco_stmts(stmts: List[Stmt]) -> List[Stmt]:
        all_stmts = []

        for stmt in stmts:
            new_stmts = []
            new_stmt = rco_stmt(stmt, new_stmts)
            all_stmts += new_stmts + [new_stmt]

        return all_stmts

    def rco_exp(e: Expr, new_stmts: List[Stmt]) -> Expr:
        match e:
            case FieldRef(o, field):
                return FieldRef(rco_exp(o, new_stmts), field)
            case Call(func, args):
                new_args = [rco_exp(e, new_stmts) for e in args]
                new_func = rco_exp(func, new_stmts)
                new_e = Call(new_func, new_args)
                new_v = gensym('tmp')
                new_stmts.append(Assign(new_v, new_e))

                if isinstance(func, Var) and func.name in function_names:
                    for cls_name, cls_type in dataclass_var_types.items():
                        if cls_name == func.name or cls_name == getattr(func, 'output_type', None):
                            dataclass_var_types[new_v] = cls_type
                            break
                return Var(new_v)
            case Var(x):
                return Var(x)
            case Constant(i):
                return Constant(i)
            case Prim(op, args):
                new_args = [rco_exp(e, new_stmts) for e in args]
                new_e = Prim(op, new_args)
                new_v = gensym('tmp')
                new_stmts.append(Assign(new_v, new_e))
                return Var(new_v)
            case _:
                raise Exception('rco_exp', e)
    match prog:
        case Program(stmts):
            return Program(rco_stmts(stmts))      


def eliminate_objects(prog: Program) -> Program:
    def elim_expr(e: Expr, local_types: Dict[str, DataclassType]) -> Expr:
        match e:
            # 1) constructor calls -> tuple
            case Call(fn, args) if isinstance(fn, Var) and fn.name in dataclass_var_types:
                return Prim('tuple', [elim_expr(a, local_types) for a in args])

            # 2) normal calls
            case Call(fn, args):
                return Call(fn, [elim_expr(a, local_types) for a in args])

            # 3) field read -> subscript
            case FieldRef(o, field):
                dt = None # default to None
                # 1) recurse into the object
                o1 = elim_expr(o, local_types)

                # 2) if it's any dataclass‐typed var (Point, p1, p2, p3)…
                if isinstance(o, Var):
                    if o.name in local_types:
                        dt = local_types[o.name]
                    elif o.name in dataclass_var_types:
                        dt = dataclass_var_types[o.name]
                    # check if this is a result of a function returning a dataclass
                    elif o.name.startswith('tmp_') or o.name in function_params.get('main', []):
                        # try to find a dataclass that has the field we're accessing
                        for cls_name, cls_type in dataclass_var_types.items():
                            if isinstance(cls_type, DataclassType) and field in cls_type.fields:
                                dt = cls_type
                                dataclass_var_types[o.name] = dt  # track this
                                break
                        
                if dt is None:
                    raise TypeError(f"Expected DataclassType or tuple for {o}, but got {dt}")

                # 4) find which field index this is, and build a subscript
                idx = list(dt.fields.keys()).index(field)
                return Prim('subscript', [o1, Constant(idx)])
            
            # 4) other prims
            case Prim(op, args):
                return Prim(op, [elim_expr(a, local_types) for a in args])

            # 5) everything else
            case _:
                return e

    def elim_stmt(s: Stmt, local_types: Dict[str, DataclassType]) -> Optional[Stmt]:
        match s:
            # drop class definitions entirely
            case ClassDef(name, superclass, body):
                dataclass_var_types[name] = DataclassType(
                    name=name,
                    fields={fname: ftype for fname, ftype in body}
                )
                return None


            # descend into function bodies, but capture params
            case FunctionDef(name, params, body, ret):
                # build new local_types for parameters
                new_locals = {
                    pname: dataclass_var_types[ptype]
                    for pname, ptype in params
                    if isinstance(ptype, str) and ptype in dataclass_var_types
                }
                new_body = [
                    elim_stmt(st, new_locals)
                    for st in body
                    if elim_stmt(st, new_locals) is not None
                ]
                return FunctionDef(name, params, new_body, ret)

            case Assign(x, e):
                return Assign(x, elim_expr(e, local_types))

            case Return(e):
                return Return(elim_expr(e, local_types))

            case Print(e):
                return Print(elim_expr(e, local_types))

            case If(cond, then_b, else_b):
                then2 = [t for t in (elim_stmt(t, local_types) for t in then_b) if t]
                else2 = [e for e in (elim_stmt(e, local_types) for e in else_b) if e]
                return If(elim_expr(cond, local_types), then2, else2)

            case While(cond, body):
                body2 = [t for t in (elim_stmt(t, local_types) for t in body) if t]
                return While(elim_expr(cond, local_types), body2)

            case _:
                return s

    # top-level: no locals
    out: List[Stmt] = []
    for top in prog.stmts:
        s2 = elim_stmt(top, {})
        if s2 is not None:
            out.append(s2)
    return Program(out)


##################################################
# explicate-control
##################################################
# op     ::= "add" | "sub" | "mult" | "not" | "or" | "and" | "eq" | "gt" | "gte" | "lt" | "lte"
#          | "subscript" | "allocate" | "collect" | "tuple_set"
# Expr   ::= Var(x) | Constant(n) | Prim(op, List[Expr])
#          | Call(Expr, List[Expr])
# Stmt   ::= Assign(x, Expr) | Print(Expr) | If(Expr, Stmts, Stmts) | While(Begin(Stmts, Expr), Stmts)
#          | Return(Expr) | FunctionDef(str, List[Tuple[str, type]], List[Stmt], type)
# Stmts  ::= List[Stmt]
# LFun   ::= Program(Stmts)

def explicate_control(prog: Program) -> cif.CProgram:
    """
    Transforms an Lfun Expression into a Cif program.
    :param prog: An Lfun Expression
    :return: A Cif Program
    """

    regular_stmts = []
    function_defs = []

    match prog:
        case Program(stmts):
            for s in stmts:
                match s:
                    case FunctionDef(name, params, body_stmts, return_type):
                        blocks = _explicate_control(name, Program(body_stmts))
                        param_names = [a[0] for a in params]
                        function_defs.append(cif.CFunctionDef(name, param_names, blocks))
                    case _:
                        regular_stmts.append(s)

            main_blocks = _explicate_control('main', Program(regular_stmts))
            function_defs.append(cif.CFunctionDef('main', [], main_blocks))

            return cif.CProgram(function_defs)

def _explicate_control(current_function: str, prog: Program) -> cif.CProgram:
    """
    Transforms an Lif Expression into a Cif program.
    :param prog: An Lif Expression
    :return: A Cif Program
    """

    # the basic blocks of the program
    basic_blocks: Dict[str, List[cif.Stmt]] = {}

    # create a new basic block to hold some statements
    # generates a brand-new name for the block and returns it
    def create_block(stmts: List[cif.Stmt]) -> str:
        label = gensym('label')
        basic_blocks[label] = stmts
        return label

    # create a new basic block to hold some statements
    # generates a brand-new name for the block and returns it
    def create_block() -> str:
        label = gensym('label')
        basic_blocks[label] = []
        return label

    # adds a statement to the end of an existing basic block
    def add_stmt(label: str, stmt: cif.Stmt):
        assert label in basic_blocks
        basic_blocks[label].append(stmt)

    def explicate_exp(e: Expr) -> cif.Expr:
        match e:
            case Call(func, args):
                new_args = [explicate_exp(a) for a in args]
                return cif.Call(explicate_exp(func), new_args)
            case Var(x):
                return cif.Var(x)
            case Constant(c):
                return cif.Constant(c)
            case Prim(op, args):
                new_args = [explicate_exp(a) for a in args]
                return cif.Prim(op, new_args)
            case _:
                raise Exception('explicate_exp', e)

    def explicate_stmt(stmt: Stmt, label: str) -> str:
        match stmt:
            case Return(e):
                new_exp = explicate_exp(e)
                add_stmt(label, cif.Return(new_exp))
                return label
            case Assign(x, exp):
                new_exp = explicate_exp(exp)
                new_stmt = cif.Assign(x, new_exp)
                add_stmt(label, new_stmt)
                return label
            case Print(exp):
                new_exp = explicate_exp(exp)
                new_stmt = cif.Print(new_exp)
                add_stmt(label, new_stmt)
                return label
            case If(condition, then_stmts, else_stmts):
                then_label = create_block()
                else_label = create_block()
                continuation_label = create_block()
                
                then_continuation = explicate_stmts(then_stmts, then_label)
                add_stmt(then_continuation, cif.Goto(continuation_label))

                else_continuation = explicate_stmts(else_stmts, else_label)
                add_stmt(else_continuation, cif.Goto(continuation_label))

                if_stmt = cif.If(explicate_exp(condition),
                                 cif.Goto(then_label),
                                 cif.Goto(else_label))
                add_stmt(label, if_stmt)
                return continuation_label
            case While(Begin(condition_stmts, condition_exp), body_stmts):
                test_label = create_block()
                body_label = create_block()
                continuation_label = create_block()

                body_continuation = explicate_stmts(body_stmts, body_label)
                add_stmt(body_continuation, cif.Goto(test_label))

                test_continuation = explicate_stmts(condition_stmts, test_label)
                add_stmt(test_continuation, cif.If(explicate_exp(condition_exp),
                                                   cif.Goto(body_label),
                                                   cif.Goto(continuation_label)))
                add_stmt(label, cif.Goto(test_label))
                return continuation_label
            case _:
                raise Exception('explicate_stmt', stmt)


    def explicate_stmts(stmts: List[Stmt], label: str) -> str:
        for s in stmts:
            label = explicate_stmt(s, label)
        return label

    match prog:
        case Program(stmts):
            basic_blocks[current_function + 'start'] = []
            conclusion_label = explicate_stmts(stmts, current_function + 'start')
            add_stmt(conclusion_label, cif.Return(cif.Constant(0)))
            return basic_blocks
        case _:
            raise RuntimeError(prog)


##################################################
# select-instructions
##################################################
# op           ::= "add" | "sub" | "mult" | "not" | "or" | "and" | "eq" | "gt" | "gte" | "lt" | "lte"
#                | "subscript" | "allocate" | "collect" | "tuple_set"
# Expr         ::= Var(x) | Constant(n) | Prim(op, List[Expr])
# Stmt         ::= Assign(x, Expr) | Print(Expr)
#                | If(Expr, Goto(label), Goto(label)) | Goto(label) | Return(Expr)
# Stmts        ::= List[Stmt]
# CFunctionDef ::= CFunctionDef(name, List[str], Dict[label, Stmts])
# Cif         ::= CProgram(List[CFunctionDef])

@dataclass(frozen=True, eq=True)
class X86FunctionDef(AST):
    label: str
    blocks: Dict[str, List[x86.Instr]]
    stack_space: Tuple[int, int]

@dataclass(frozen=True, eq=True)
class X86ProgramDefs(AST):
    defs: List[X86FunctionDef]

def select_instructions(prog: cif.CProgram) -> X86ProgramDefs:
    """
    Transforms a Lfun program into a pseudo-x86 assembly program.
    :param prog: a Lfun program
    :return: a pseudo-x86 program
    """

    function_defs = []

    match prog:
        case cif.CProgram(defs):
            for d in defs:
                match d:
                    case cif.CFunctionDef(name, args, blocks):
                        p = _select_instructions(name, cif.CProgram(blocks))
                        match p:
                            case x86.X86Program(new_blocks):
                                setup_instrs = [x86.Movq(x86.Reg(r), x86.Var(a)) \
                                                for a, r in zip(args, constants.argument_registers)]
                                new_blocks[name + 'start'] = setup_instrs + new_blocks[name + 'start']

                                function_defs.append(X86FunctionDef(name, new_blocks, None))
            return X86ProgramDefs(function_defs)


def _select_instructions(current_function: str, prog: cif.CProgram) -> x86.X86Program:
    """
    Transforms a Cif program into a pseudo-x86 assembly program.
    :param prog: a Cif program
    :return: a pseudo-x86 program
    """

    def mk_tag(types: Tuple[type]) -> int:
        """
        Builds a vector tag. See section 5.2.2 in the textbook.
        :param types: A list of the types of the vector's elements.
        :return: A vector tag, as an integer.
        """
        pointer_mask = 0
        # for each type in the vector, encode it in the pointer mask
        for t in reversed(types):
            # shift the mask by 1 bit to make room for this type
            pointer_mask = pointer_mask << 1

            if isinstance(t, tuple):
                # if it's a vector type, the mask is 1
                pointer_mask = pointer_mask + 1
            else:
                # otherwise, the mask is 0 (do nothing)
                pass

        # shift the pointer mask by 6 bits to make room for the length field
        mask_and_len = pointer_mask << 6
        mask_and_len = mask_and_len + len(types) # add the length

        # shift the mask and length by 1 bit to make room for the forwarding bit
        tag = mask_and_len << 1
        tag = tag + 1

        return tag

    def si_expr(a: cif.Expr) -> x86.Arg:
        match a:
            case cif.Constant(i):
                return x86.Immediate(int(i))

            case cif.Var(x):
                # if x is one of this function’s parameters, return its arg‐reg
                params = function_params.get(current_function, [])
                if x in params:
                    idx = params.index(x)
                    reg_name = constants.argument_registers[idx]
                    return x86.Reg(reg_name)
                # otherwise keep it as a Var
                return x86.Var(x)

            case cif.Prim('subscript', [arr, cif.Constant(idx)]):
                base = si_expr(arr)
                offset = 8 * (int(idx) + 1)
                
                if isinstance(base, x86.Reg):
                    return x86.Deref(base.val, offset)
                elif isinstance(base, x86.Var):
                    return x86.Deref('r11', offset)
                else:
                    return x86.Deref(base, offset)

            case _:
                raise Exception('si_expr', a)


    def si_stmts(stmts: List[cif.Stmt]) -> List[x86.Instr]:
        instrs = []

        for stmt in stmts:
            instrs.extend(si_stmt(stmt))

        return instrs

    op_cc = {'eq': 'e', 'gt': 'g', 'gte': 'ge', 'lt': 'l', 'lte': 'le'}

    binop_instrs = {'add': x86.Addq, 'sub': x86.Subq, 'mult': x86.Imulq,
                    'and': x86.Andq, 'or': x86.Orq}

    def si_stmt(stmt: cif.Stmt) -> List[x86.Instr]:
        match stmt:
            case cif.Assign(x, cif.Var(f)) if f in function_names:
                return [x86.Leaq(x86.GlobalVal(f), x86.Var(x))]
            case cif.Assign(x, cif.Call(fun, args)):
                instrs = []

                # save caller-saved registers
                for r in constants.caller_saved_registers:
                    instrs += [x86.Pushq(x86.Reg(r))]

                # place arguments in argument registers
                for a, r in zip(args, constants.argument_registers):
                    instrs += [x86.Movq(si_expr(a), x86.Reg(r))]

                # call the function
                match fun:
                    case cif.Var(f) if f in function_names:
                        instrs += [x86.Callq(f)]
                    case _:
                        instrs += [x86.IndirectCallq(si_expr(fun), 0)]

                # restore caller-saved registers
                for r in reversed(constants.caller_saved_registers):
                    instrs += [x86.Popq(x86.Reg(r))]

                # move the result from rax into the destination
                instrs += [x86.Movq(x86.Reg('rax'), x86.Var(x))]
                return instrs
            case cif.Assign(x, cif.Prim('tuple', args)):
                tag = mk_tag(tuple_var_types[x])
                instrs = [x86.Movq(x86.Immediate(8*(1+len(args))), x86.Reg('rdi')),
                          x86.Callq('allocate'),
                          x86.Movq(x86.Reg('rax'), x86.Reg('r11')),
                          x86.Movq(x86.Immediate(tag), x86.Deref('r11', 0))]
                for i, a in enumerate(args):
                    instrs.append(x86.Movq(si_expr(a), x86.Deref('r11', 8*(i+1))))
                instrs.append(x86.Movq(x86.Reg('r11'), x86.Var(x)))
                return instrs
            case cif.Assign(x, cif.Prim('subscript', [atm1, cif.Constant(idx)])):
                offset_bytes = 8 * (idx + 1)
                return [x86.Movq(si_expr(atm1), x86.Reg('r11')),
                        x86.Movq(x86.Deref('r11', offset_bytes), x86.Var(x))]
            case cif.Assign(x, cif.Prim(op, [atm1, atm2])):
                if op in binop_instrs:
                    return [x86.Movq(si_expr(atm1), x86.Reg('rax')),
                            binop_instrs[op](si_expr(atm2), x86.Reg('rax')),
                            x86.Movq(x86.Reg('rax'), x86.Var(x))]
                elif op in op_cc:
                    return [x86.Cmpq(si_expr(atm2), si_expr(atm1)),
                            x86.Set(op_cc[op], x86.ByteReg('al')),
                            x86.Movzbq(x86.ByteReg('al'), x86.Var(x))]

                else:
                    raise Exception('si_stmt failed op', op)
            case cif.Assign(x, cif.Prim('not', [atm1])):
                return [x86.Movq(si_expr(atm1), x86.Var(x)),
                        x86.Xorq(x86.Immediate(1), x86.Var(x))]
            case cif.Assign(x, atm1):
                return [x86.Movq(si_expr(atm1), x86.Var(x))]
            case cif.Print(atm1):
                return [x86.Movq(si_expr(atm1), x86.Reg('rdi')),
                        x86.Callq('print_int')]
            case cif.Return(atm1):
                return [x86.Movq(si_expr(atm1), x86.Reg('rax')),
                        x86.Jmp(current_function + 'conclusion')]
            case cif.Goto(label):
                return [x86.Jmp(label)]
            case cif.If(a, cif.Goto(then_label), cif.Goto(else_label)):
                return [x86.Cmpq(si_expr(a), x86.Immediate(1)),
                        x86.JmpIf('e', then_label),
                        x86.Jmp(else_label)]
            case _:
                raise Exception('si_stmt', stmt)

    match prog:
        case cif.CProgram(basic_blocks):
            basic_blocks = {label: si_stmts(block) for (label, block) in basic_blocks.items()}
            return x86.X86Program(basic_blocks)
        case _:
            raise Exception('select_instructions', prog)


##################################################
# allocate-registers
##################################################
# Arg    ::= Immediate(i) | Reg(r) | ByteReg(r) | Var(x) | Deref(r, offset) | GlobalVal(x)
# op     ::= 'addq' | 'cmpq' | 'andq' | 'orq' | 'xorq' | 'movq' | 'movzbq' | 'leaq'
# cc     ::= 'e'| 'g' | 'ge' | 'l' | 'le'
# Instr  ::= op(Arg, Arg) | Callq(label) | Retq()
#         | Jmp(label) | JmpIf(cc, label) | Set(cc, Arg)
#         | Jmp(label) | JmpIf(cc, label) | Set(cc, Arg)
#         | IndirectCallq(Arg)
# Blocks ::= Dict[label, List[Instr]]

# X86FunctionDef ::= X86FunctionDef(name, Blocks)
# X86ProgramDefs ::= List[X86FunctionDef]

Color = int
Coloring = Dict[x86.Var, Color]
Saturation = Set[Color]

def allocate_registers(program: X86ProgramDefs) -> X86ProgramDefs:
    """
    Assigns homes to variables in the input program. Allocates registers and
    stack locations as needed, based on a graph-coloring register allocation
    algorithm.
    :param program: A pseudo-x86 program.
    :return: An x86 program, annotated with the number of bytes needed in stack
    locations.
    """

    match program:
        case X86ProgramDefs(defs):
            new_defs = []
            for d in defs:
                new_program = _allocate_registers(d.label, x86.X86Program(d.blocks))
                new_defs.append(X86FunctionDef(d.label, new_program.blocks, new_program.stack_space))
            return X86ProgramDefs(new_defs)


def _allocate_registers(current_function: str, program: x86.X86Program) -> x86.X86Program:
    """
    Assigns homes to variables in the input program. Allocates registers and
    stack locations as needed, based on a graph-coloring register allocation
    algorithm.
    :param program: A pseudo-x86 program.
    :return: An x86 program, annotated with the number of bytes needed in stack
    locations.
    """

    blocks = program.blocks
    live_before_sets = {current_function + 'conclusion': set()}
    for label in blocks:
        live_before_sets[label] = set()
    live_after_sets = {}
    homes: Dict[x86.Var, x86.Arg] = {}
    tuple_homes: Dict[x86.Var, x86.Arg] = {}
    tuple_vars = set(tuple_var_types.keys())

    # --------------------------------------------------
    # utilities
    # --------------------------------------------------
    def vars_arg(a: x86.Arg) -> Set[x86.Var]:
        match a:
            case x86.Immediate(i):
                return set()
            case x86.GlobalVal(v):
                return set()
            case x86.Reg(r):
                return set()
            case x86.ByteReg(r):
                return set()
            case x86.Var(x):
                return { x86.Var(x) } if x not in tuple_var_types else set()
            case x86.Deref(x86.Var(x), _offset):
                return { x86.Var(x) } if x not in tuple_var_types else set()
            case x86.Deref(_, _):
                return set()
            case _:
                return set()

    def reads_of(i: x86.Instr) -> Set[x86.Var]:
        match i:
            case x86.Movq(e1, _) | x86.Movzbq(e1, _) | x86.Pushq(e1) | x86.IndirectCallq(e1):
                return vars_arg(e1)
            case x86.Addq(e1, e2) | x86.Cmpq(e1, e2) | x86.Imulq(e1, e2) | \
                 x86.Subq(e1, e2) | x86.Andq(e1, e2) | x86.Orq(e1, e2) | x86.Xorq(e1, e2) | \
                 x86.Leaq(e1, e2):
                return vars_arg(e1).union(vars_arg(e2))
            case x86.Jmp(label) | x86.JmpIf(_, label):
                # the variables that might be read after this instruction
                # are the live-before variables of the destination block
                return live_before_sets[label]
            case _:
                if isinstance(i, (x86.Callq, x86.Set, x86.Popq)):
                    return set()
                else:
                    raise Exception(i)

    def writes_of(i: x86.Instr) -> Set[x86.Var]:
        match i:
            case x86.Movq(_, e2) | x86.Movzbq(_, e2) | \
                 x86.Addq(_, e2) | x86.Cmpq(_, e2) | x86.Imulq(_, e2) | \
                 x86.Subq(_, e2) | x86.Andq(_, e2) | x86.Orq(_, e2) | x86.Xorq(_, e2) | \
                 x86.Popq(e2) | x86.Leaq(_, e2):
                return vars_arg(e2)
            case _:
                if isinstance(i, (x86.Jmp, x86.JmpIf, x86.Callq, x86.Set, x86.IndirectCallq,
                                  x86.Pushq)):
                    return set()
                else:
                    raise Exception(i)

    # --------------------------------------------------
    # liveness analysis
    # --------------------------------------------------
    def ul_instr(i: x86.Instr, live_after: Set[x86.Var]) -> Set[x86.Var]:
        return live_after.difference(writes_of(i)).union(reads_of(i))

    def ul_block(label: str):
        instrs = blocks[label]
        current_live_after: Set[x86.Var] = set()

        block_live_after_sets = []
        for i in reversed(instrs):
            block_live_after_sets.append(current_live_after)
            current_live_after = ul_instr(i, current_live_after)

        live_before_sets[label] = current_live_after
        live_after_sets[label] = list(reversed(block_live_after_sets))

    def ul_fixpoint():
        labels = list(blocks.keys())
        fixpoint_reached = False

        while not fixpoint_reached:
            old_live_befores = live_before_sets.copy()

            for label in labels:
                ul_block(label)

            if old_live_befores == live_before_sets:
                fixpoint_reached = True

    # --------------------------------------------------
    # interference graph
    # --------------------------------------------------
    def bi_instr(e: x86.Instr, live_after: Set[x86.Var], graph: InterferenceGraph):
        for v1 in writes_of(e):
            for v2 in live_after:
                graph.add_edge(v1, v2)

    def bi_block(instrs: List[x86.Instr], live_afters: List[Set[x86.Var]], graph: InterferenceGraph):
        for instr, live_after in zip(instrs, live_afters):
            bi_instr(instr, live_after, graph)

    # --------------------------------------------------
    # graph coloring
    # --------------------------------------------------
    def color_graph(local_vars: Set[x86.Var], interference_graph: InterferenceGraph) -> Coloring:
        coloring: Coloring = {}

        to_color = local_vars.copy()

        # Saturation sets start out empty
        saturation_sets = {x: set() for x in local_vars}

        # Loop until we are finished coloring
        while to_color:
            # Find the variable x with the largest saturation set
            x = max(to_color, key=lambda x: len(saturation_sets[x]))

            # Remove x from the variables to color
            to_color.remove(x)

            # Find the smallest color not in x's saturation set
            x_color = next(i for i in itertools.count() if i not in saturation_sets[x])

            # Assign x's color
            coloring[x] = x_color

            # Add x's color to the saturation sets of its neighbors
            for y in interference_graph.neighbors(x):
                saturation_sets[y].add(x_color)

        return coloring

    # --------------------------------------------------
    # assigning homes
    # --------------------------------------------------
    def align(num_bytes: int) -> int:
        if num_bytes % 16 == 0:
            return num_bytes
        else:
            return num_bytes + (16 - (num_bytes % 16))

    def ah_arg(a: x86.Arg) -> x86.Arg:
        match a:
            case x86.Immediate(_) | x86.GlobalVal(_) | x86.Reg(_) | x86.ByteReg(_):
                return a
            case x86.Var(x):
                if x in tuple_vars:
                    if x in tuple_homes:
                        return tuple_homes[x]
                    else:
                        current_stack_size = len(tuple_homes) * 8
                        offset = -(current_stack_size + 8)
                        tuple_homes[x] = x86.Deref('r15', offset)
                        return x86.Deref('r15', offset)
                else:
                    if a in homes:
                        return homes[a]
                    else:
                        return x86.Reg('r8')
            case x86.Deref(r, offset):
                return a
            case _:
                raise Exception('ah_arg', a)

    def ah_instr(e: x86.Instr) -> x86.Instr:
        match e:
            case x86.Movq(a1, a2):
                return x86.Movq(ah_arg(a1), ah_arg(a2))
            case x86.Movzbq(a1, a2):
                return x86.Movzbq(ah_arg(a1), ah_arg(a2))
            case x86.Addq(a1, a2):
                return x86.Addq(ah_arg(a1), ah_arg(a2))
            case x86.Subq(a1, a2):
                return x86.Subq(ah_arg(a1), ah_arg(a2))
            case x86.Imulq(a1, a2):
                return x86.Imulq(ah_arg(a1), ah_arg(a2))
            case x86.Cmpq(a1, a2):
                return x86.Cmpq(ah_arg(a1), ah_arg(a2))
            case x86.Andq(a1, a2):
                return x86.Andq(ah_arg(a1), ah_arg(a2))
            case x86.Orq(a1, a2):
                return x86.Orq(ah_arg(a1), ah_arg(a2))
            case x86.Xorq(a1, a2):
                return x86.Xorq(ah_arg(a1), ah_arg(a2))
            case x86.Set(cc, a1):
                return x86.Set(cc, ah_arg(a1))
            case x86.Pushq(a1):
                return x86.Pushq(ah_arg(a1))
            case x86.Popq(a1):
                return x86.Popq(ah_arg(a1))
            case x86.IndirectCallq(a1, i):
                return x86.IndirectCallq(ah_arg(a1), i)
            case x86.Leaq(a1, a2):
                return x86.Leaq(ah_arg(a1), ah_arg(a2))
            case _:
                if isinstance(e, (x86.Callq, x86.Retq, x86.Jmp, x86.JmpIf)):
                    return e
                else:
                    raise Exception('ah_instr', e)

    def ah_block(instrs: List[x86.Instr]) -> List[x86.Instr]:
        return [ah_instr(i) for i in instrs]

    # --------------------------------------------------
    # main body of the pass
    # --------------------------------------------------

    # Step 1: Perform liveness analysis
    ul_fixpoint()
    log_ast('live-after sets', live_after_sets)

    # Step 2: Build the interference graph
    interference_graph = InterferenceGraph()

    for label in blocks.keys():
        bi_block(blocks[label], live_after_sets[label], interference_graph)

    log_ast('interference graph', interference_graph)

    # Step 3: Color the graph
    all_vars = interference_graph.get_nodes()
    coloring = color_graph(all_vars, interference_graph)
    colors_used = set(coloring.values())
    log('coloring', coloring)

    # Defines the set of registers to use
    available_registers = constants.caller_saved_registers + constants.callee_saved_registers

    # Step 4: map variables to homes
    color_map = {}
    stack_locations_used = 0

    # Step 4.1: Map colors to locations (the "color map")
    for color in sorted(colors_used):
        if available_registers != []:
            r = available_registers.pop()
            color_map[color] = x86.Reg(r)
        else:
            offset = stack_locations_used+1
            color_map[color] = x86.Deref('rbp', -(offset * 8))
            stack_locations_used += 1

    # Step 4.2: Compose the "coloring" with the "color map" to get "homes"
    for v in all_vars:
        homes[v] = color_map[coloring[v]]
    log('homes', homes)
    
    # Step 5: replace variables with their homes
    blocks = program.blocks
    new_blocks = {label: ah_block(block) for label, block in blocks.items()}

    regular_stack_space = align(8 * stack_locations_used)
    root_stack_slots = len(tuple_homes)
    
    arg_regs = constants.argument_registers
    for idx, param_name in enumerate(function_params.get(current_function, [])):
        homes[param_name] = x86.Reg(arg_regs[idx])
    _homes[current_function] = homes

    return x86.X86Program(new_blocks, stack_space = (regular_stack_space, root_stack_slots))



##################################################
# patch-instructions
##################################################
# Arg    ::= Immediate(i) | Reg(r) | ByteReg(r) | Var(x) | Deref(r, offset) | GlobalVal(x)
# op     ::= 'addq' | 'cmpq' | 'andq' | 'orq' | 'xorq' | 'movq' | 'movzbq' | 'leaq'
# cc     ::= 'e'| 'g' | 'ge' | 'l' | 'le'
# Instr  ::= op(Arg, Arg) | Callq(label) | Retq()
#         | Jmp(label) | JmpIf(cc, label) | Set(cc, Arg)
#         | Jmp(label) | JmpIf(cc, label) | Set(cc, Arg)
#         | IndirectCallq(Arg)
# Blocks ::= Dict[label, List[Instr]]

# X86FunctionDef ::= X86FunctionDef(name, Blocks)
# X86ProgramDefs ::= List[X86FunctionDef]

def patch_instructions(program: X86ProgramDefs) -> X86ProgramDefs:
    """
    Patches instructions with two memory location inputs, using %rax as a temporary location.
    :param program: An x86 program.
    :return: A patched x86 program.
    """

    match program:
        case X86ProgramDefs(defs):
            new_defs = []
            for d in defs:
                homes = _homes.get(d.label, {})
                new_prog = _patch_instructions(x86.X86Program(d.blocks), homes)
                new_defs.append(X86FunctionDef(d.label, new_prog.blocks, d.stack_space))
            return X86ProgramDefs(new_defs)


def _patch_instructions(program: x86.X86Program, homes: Dict[x86.Var, x86.Arg]) -> x86.X86Program:
    """
    Patches instructions with two memory location inputs, using %rax as a temporary location.
    :param program: An x86 program.
    :return: A patched x86 program.
    """
    def patch_arg(a: x86.Arg) -> x86.Arg:
        match a:
            case x86.Var(x) if x in homes:
                return homes[x]     
            case x86.Deref(x86.Var(x), off) if x in homes:
                return x86.Deref(homes[x], off)
            case _:
                return a


    def pi_instr(instr: x86.Instr) -> List[x86.Instr]:
        instr = instr.__class__(*(patch_arg(arg) for arg in instr.args)) if hasattr(instr, 'args') else instr
        match instr:
            case x86.Cmpq(a1, x86.Immediate(i)):
                return [x86.Movq(x86.Immediate(i), x86.Reg('rax')),
                        x86.Cmpq(a1, x86.Reg('rax'))]
            case x86.Movq(x86.Deref(r1, o1), x86.Deref(r2, o2)):
                return [x86.Movq(x86.Deref(r1, o1), x86.Reg('rax')),
                        x86.Movq(x86.Reg('rax'), x86.Deref(r2, o2))]
            case x86.Movzbq(x86.Deref(r1, o1), x86.Deref(r2, o2)):
                return [x86.Movzbq(x86.Deref(r1, o1), x86.Reg('rax')),
                        x86.Movq(x86.Reg('rax'), x86.Deref(r2, o2))]
            case x86.Addq(x86.Deref(r1, o1), x86.Deref(r2, o2)):
                return [x86.Movq(x86.Deref(r1, o1), x86.Reg('rax')),
                        x86.Addq(x86.Reg('rax'), x86.Deref(r2, o2))]
            case _:
                return [instr]


    def pi_block(instrs: List[x86.Instr]) -> List[x86.Instr]:
        new_instrs = []
        for i in instrs:
            new_instrs.extend(pi_instr(i))
        return new_instrs

    match program:
        case x86.X86Program(blocks, stack_space):
            new_blocks = {label: pi_block(block) for label, block in blocks.items()}
            return x86.X86Program(new_blocks, stack_space = stack_space)


##################################################
# prelude-and-conclusion
###################################################
# Arg    ::= Immediate(i) | Reg(r) | ByteReg(r) | Var(x) | Deref(r, offset) | GlobalVal(x)
# op     ::= 'addq' | 'cmpq' | 'andq' | 'orq' | 'xorq' | 'movq' | 'movzbq' | 'leaq'
# cc     ::= 'e'| 'g' | 'ge' | 'l' | 'le'
# Instr  ::= op(Arg, Arg) | Callq(label) | Retq()
#         | Jmp(label) | JmpIf(cc, label) | Set(cc, Arg)
#         | Jmp(label) | JmpIf(cc, label) | Set(cc, Arg)
#         | IndirectCallq(Arg)
# Blocks ::= Dict[label, List[Instr]]

# X86FunctionDef ::= X86FunctionDef(name, Blocks)
# X86ProgramDefs ::= List[X86FunctionDef]

def prelude_and_conclusion(program: X86ProgramDefs) -> x86.X86Program:
    """
    Adds the prelude and conclusion for the program.
    :param program: An x86 program.
    :return: An x86 program, with prelude and conclusion.
    """

    match program:
        case X86ProgramDefs(defs):
            all_blocks = {}
            for d in defs:
                new_prog = _prelude_and_conclusion(d.label, x86.X86Program(d.blocks, d.stack_space))
                match new_prog:
                    case x86.X86Program(blocks):
                        for label, instrs in blocks.items():
                            all_blocks[label] = instrs
            return x86.X86Program(all_blocks)


def _prelude_and_conclusion(current_function: str, program: x86.X86Program) -> x86.X86Program:
    """
    Adds the prelude and conclusion for the program.
    :param program: An x86 program.
    :return: An x86 program, with prelude and conclusion.
    """
    stack_bytes, root_stack_locations = program.stack_space

    # Prelude
    prelude = [x86.Pushq(x86.Reg('rbp')),
               x86.Movq(x86.Reg('rsp'), x86.Reg('rbp'))]

    for r in constants.callee_saved_registers:
        prelude += [x86.Pushq(x86.Reg(r))]

    prelude += [x86.Subq(x86.Immediate(stack_bytes), x86.Reg('rsp'))]

    if current_function == 'main':
        prelude += [x86.Movq(x86.Immediate(constants.root_stack_size), x86.Reg('rdi')),
                    x86.Movq(x86.Immediate(constants.heap_size), x86.Reg('rsi')),
                    x86.Callq('initialize'),
                    x86.Movq(x86.GlobalVal('rootstack_begin'), x86.Reg('r15'))]

    for _ in range(root_stack_locations):
        prelude += [x86.Movq(x86.Immediate(0), x86.Deref('r15', 0)),
                    x86.Addq(x86.Immediate(8), x86.Reg('r15'))]
    prelude += [x86.Jmp(current_function + 'start')]

    # Conclusion
    conclusion = [x86.Addq(x86.Immediate(stack_bytes), x86.Reg('rsp')),
                  x86.Subq(x86.Immediate(8*root_stack_locations), x86.Reg('r15'))]

    for r in reversed(constants.callee_saved_registers):
        conclusion += [x86.Popq(x86.Reg(r))]

    conclusion += [x86.Popq(x86.Reg('rbp')),
                   x86.Retq()]

    new_blocks = program.blocks.copy()
    new_blocks[current_function] = prelude
    new_blocks[current_function + 'conclusion'] = conclusion
    return x86.X86Program(new_blocks, stack_space = program.stack_space)


##################################################
# add-allocate
##################################################

def add_allocate(program: str) -> str:
    """
    Adds the 'allocate' function to the end of the program.
    :param program: An x86 program, as a string.
    :return: An x86 program, as a string, with the 'allocate' function.
    """

    alloc = """
allocate:
  movq free_ptr(%rip), %rax
  addq %rdi, %rax
  movq %rdi, %rsi
  cmpq fromspace_end(%rip), %rax
  jl allocate_alloc
  movq %r15, %rdi
  callq collect
  jmp allocate_alloc
allocate_alloc:
  movq free_ptr(%rip), %rax
  addq %rsi, free_ptr(%rip)
  retq
"""
    return program + alloc

##################################################
# Compiler definition
##################################################

compiler_passes = {
    'typecheck': typecheck,
    'remove complex opera*': rco,
    'eliminate objects': eliminate_objects,
    'typecheck2': typecheck,
    'explicate control': explicate_control,
    'select instructions': select_instructions,
    'allocate registers': allocate_registers,
    'patch instructions': patch_instructions,
    'prelude & conclusion': prelude_and_conclusion,
    'print x86': x86.print_x86,
    'add allocate': add_allocate
}


def run_compiler(s, logging=False):
    global tuple_var_types, function_names, dataclass_var_types
    tuple_var_types = {}
    dataclass_var_types = {}
    function_names = set()

    def print_prog(current_program):
        print('Concrete syntax:')
        if isinstance(current_program, x86.X86Program):
            print(x86.print_x86(current_program))
        elif isinstance(current_program, X86ProgramDefs):
            print(print_x86defs.print_x86_defs(current_program))
        elif isinstance(current_program, Program):
            print(print_program(current_program))
        elif isinstance(current_program, cif.CProgram):
            print(cif.print_program(current_program))

        print()
        print('Abstract syntax:')
        print(print_ast(current_program))
            
        if debug_sets:
            print("\n{:<25} {:<40}".format("Dataclass Name", "Fields"))
            print("-" * 65)
            for name, fields in dataclass_var_types.items():
                print("{:<25} {:<40}".format(str(name), str(fields)))

            print("\n\n{:<25} {:<40}".format("Function Name", "Return Type"))
            print("-" * 65)
            for name, ret_type in function_return_types.items():
                print("{:<25} {:<40}".format(str(name), str(ret_type)))

            print("\n\n{:<25} {:<40}".format("Function Name", "Parameters"))
            print("-" * 65)
            for key, value in function_params.items():
                print("{:<25} {:<40}".format(str(key), str(value)))
            print("\n")

            # print("\n\n{:<25} {:<40}".format("Tuple Name", "Fields"))
            # print("-" * 65)
            # for key, value in tuple_var_types.items():
            #     print("{:<25} {:<40}".format(str(key), str(value)))
                
    current_program = parse(s)

    if logging == True:
        print()
        print('==================================================')
        print(' Input program')
        print('==================================================')
        print()
        print_prog(current_program)

    for pass_name, pass_fn in compiler_passes.items():
        current_program = pass_fn(current_program)

        if logging == True:
            print()
            print('==================================================')
            print(f' Output of pass: {pass_name}')
            print('==================================================')
            print()
            print_prog(current_program)

    return current_program


if __name__ == '__main__':
    if len(sys.argv) != 2:
        print('Usage: python compiler.py <source filename>')
    else:
        file_name = sys.argv[1]
        with open(file_name) as f:
            print(f'Compiling program {file_name}...')

            try:
                program = f.read()
                x86_program = run_compiler(program, logging=True)

                with open(file_name + '.s', 'w') as output_file:
                    output_file.write(x86_program)

            except:
                print('Error during compilation! **************************************************')
                traceback.print_exception(*sys.exc_info())
