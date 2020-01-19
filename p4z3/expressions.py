from copy import deepcopy, copy
from collections import OrderedDict
import operator as op
import z3

from p4z3.base import log, step, P4ComplexType, Enum, Struct, P4Package


def resolve_expr(p4_state, expr):
    # Resolves to z3 and z3p4 expressions, ints, lists, and dicts are also okay
    # resolve potential string references first
    log.debug("Resolving %s", expr)
    if isinstance(expr, str):
        val = p4_state.resolve_reference(expr)
        if val is None:
            raise RuntimeError(f"Value {expr} could not be found!")
    else:
        val = expr
    if isinstance(val, (z3.AstRef, int)):
        # These are z3 types and can be returned
        # Unfortunately int is part of it because z3 is very inconsistent
        # about var handling...
        return val
    if isinstance(val, P4ComplexType):
        # If we get a whole class return a new reference to the object
        # Do not return the z3 type because we may assign a complete structure
        if isinstance(val, Struct):
            return copy(val)
        return val
    if isinstance(val, P4Expression):
        # We got a P4 type, recurse...
        val = val.eval(p4_state)
        return resolve_expr(p4_state, val)
    if isinstance(val, list):
        # For lists, resolve each value individually and return a new list
        list_expr = []
        for val_expr in val:
            rval_expr = resolve_expr(p4_state, val_expr)
            list_expr.append(rval_expr)
        return list_expr
    if isinstance(val, dict):
        # For dicts, resolve each value individually and return a new dict
        dict_expr = []
        for name, val_expr in val.items():
            rval_expr = resolve_expr(p4_state, val_expr)
            dict_expr[name] = rval_expr
        return dict_expr
    raise TypeError(f"Value of type {type(val)} cannot be resolved!")


def resolve_action(action_expr):
    # TODO Fix this roundabout way of getting a P4 Action, super annoying...
    if isinstance(action_expr, MethodCallExpr):
        action_name = action_expr.p4_method
        action_args = action_expr.args
    elif isinstance(action_expr, str):
        action_name = action_expr
        action_args = []
    else:
        raise TypeError(
            f"Expected a method call, got {type(action_name)}!")
    return action_name, action_args


def get_type(p4_state, expr):
    ''' Return the type of an expression, Resolve, if needed'''
    arg_expr = resolve_expr(p4_state, expr)
    if isinstance(arg_expr, P4ComplexType):
        arg_type = arg_expr.z3_type
    elif isinstance(arg_expr, int):
        arg_type = z3.IntSort()
    else:
        arg_type = arg_expr.sort()
    return arg_type


def z3_implies(p4_state, cond, then_expr):
    log.debug("Evaluating no_match...")
    no_match = step(p4_state)
    return z3.If(cond, then_expr, no_match)


def check_p4_type(expr):
    if isinstance(expr, P4ComplexType):
        expr = expr.get_z3_repr()
    return expr


def align_bitvecs(bitvec1, bitvec2, p4_state):
    if isinstance(bitvec1, z3.BitVecRef) and isinstance(bitvec2, z3.BitVecRef):
        if bitvec1.size() < bitvec2.size():
            bitvec1 = P4Cast(bitvec1, bitvec2.size()).eval(p4_state)
        if bitvec1.size() > bitvec2.size():
            bitvec2 = P4Cast(bitvec2, bitvec1.size()).eval(p4_state)
    return bitvec1, bitvec2


def z3_cast(val, to_type):

    if isinstance(val, (z3.BoolSortRef, z3.BoolRef)):
        # Convert boolean variables to a bit vector representation
        # TODO: Streamline bools and their evaluation
        val = z3.If(val, z3.BitVecVal(1, 1), z3.BitVecVal(0, 1))

    if isinstance(to_type, z3.BoolSortRef):
        # casting to a bool is simple, just check if the value is equal to 1
        # this works for bitvectors and integers, we convert any bools before
        return val == z3.BitVecVal(1, 1)

    # from here on we assume we are working with integer or bitvector types
    if isinstance(to_type, (z3.BitVecSortRef)):
        # It can happen that we get a bitvector type as target, get its size.
        to_type_size = to_type.size()
    else:
        to_type_size = to_type

    if isinstance(val, int):
        # It can happen that we get an int, cast it to a bit vector.
        return z3.BitVecVal(val, to_type_size)
    val_size = val.size()

    if val_size < to_type_size:
        # the target value is larger, extend with zeros
        return z3.ZeroExt(to_type_size - val_size, val)
    else:
        # the target value is smaller, truncate everything on the right
        return z3.Extract(to_type_size - 1, 0, val)


def slice_assign(lval, rval, slice_l, slice_r) -> z3.SortRef:
    # stupid integer checks that are unfortunately necessary....
    if isinstance(lval, int):
        lval = z3.BitVecVal(lval, 64)
    lval_max = lval.size() - 1
    if slice_l == lval_max and slice_r == 0:
        # slice is full lvalue, nothing to do
        return rval
    assemble = []
    if slice_l < lval_max:
        # left slice is smaller than the max, leave that chunk unchanged
        assemble.append(z3.Extract(lval_max, slice_l + 1, lval))
    # fill the rval into the slice
    rval = z3_cast(rval, slice_l + 1 - slice_r)
    assemble.append(rval)
    if slice_r > 0:
        # right slice is larger than zero, leave that chunk unchanged
        assemble.append(z3.Extract(slice_r - 1, 0, lval))
    return z3.Concat(*assemble)


class P4Instance():
    def __new__(cls, z3_reg, method_name, *args, **kwargs):
        # parsed_args = []
        # for arg in args:
        #     arg = z3_reg._globals[arg]
        #     parsed_args.append(arg)
        # parsed_kwargs = {}
        # for name, arg in kwargs:
        #     arg = z3_reg._globals[arg]
        #     parsed_kwargs[name] = arg
        return z3_reg._globals[method_name](None, *args, **kwargs)


class P4Z3Class():
    def eval(self, p4_state):
        raise NotImplementedError("Method eval not implemented!")


class P4Expression(P4Z3Class):
    pass


class P4Statement(P4Z3Class):
    pass


class P4Op(P4Expression):
    def get_value():
        raise NotImplementedError("get_value")

    def eval(self, p4_state):
        raise NotImplementedError("eval")


class P4BinaryOp(P4Op):
    def __init__(self, lval, rval, operator):
        self.lval = lval
        self.rval = rval
        self.operator = operator

    def get_value(self):
        # TODO: This is a kind of hacky function to work around bitvectors
        # There must be a better way to implement this
        lval = self.lval
        rval = self.rval
        if isinstance(lval, P4Op):
            lval = lval.get_value()
        if isinstance(rval, P4Op):
            rval = rval.get_value()
        if isinstance(lval, int) and isinstance(rval, int):
            return self.operator(lval, rval)
        else:
            raise RuntimeError(
                f"Operations on {lval} or {rval} not supported!")

    def eval(self, p4_state):
        lval_expr = resolve_expr(p4_state, self.lval)
        rval_expr = resolve_expr(p4_state, self.rval)

        # if we compare to enums, do not use them for operations
        # for some reason, overloading equality does not work here...
        # instead reference a named bitvector of size 8
        # this represents a choice
        lval_expr, rval_expr = align_bitvecs(
            lval_expr, rval_expr, p4_state)
        return self.operator(lval_expr, rval_expr)


class P4UnaryOp(P4Op):
    def __init__(self, val, operator):
        self.val = val
        self.operator = operator

    def get_value(self):
        val = self.val
        if isinstance(val, P4Op):
            val = val.get_value()
        if isinstance(val, int):
            return self.operator(val)
        else:
            raise RuntimeError(f"Operations on {val}not supported!")

    def eval(self, p4_state):
        expr = resolve_expr(p4_state, self.val)
        return self.operator(expr)


class P4not(P4UnaryOp):
    def __init__(self, val):
        operator = z3.Not
        P4UnaryOp.__init__(self, val, operator)


class P4abs(P4UnaryOp):
    def __init__(self, val):
        operator = op.abs
        P4UnaryOp.__init__(self, val, operator)


class P4inv(P4UnaryOp):
    def __init__(self, val):
        operator = op.inv
        P4UnaryOp.__init__(self, val, operator)


class P4neg(P4UnaryOp):
    def __init__(self, val):
        operator = op.neg
        P4UnaryOp.__init__(self, val, operator)


class P4add(P4BinaryOp):
    def __init__(self, lval, rval):
        operator = op.add
        P4BinaryOp.__init__(self, lval, rval, operator)


class P4sub(P4BinaryOp):
    def __init__(self, lval, rval):
        operator = op.sub
        P4BinaryOp.__init__(self, lval, rval, operator)


class P4addsat(P4BinaryOp):
    # TODO: Not sure if this is right, check eventually
    def __init__(self, lval, rval):
        operator = (lambda x, y: z3.BVAddNoOverflow(x, y, False))
        operator = op.add
        P4BinaryOp.__init__(self, lval, rval, operator)


class P4subsat(P4BinaryOp):
    # TODO: Not sure if this is right, check eventually
    def __init__(self, lval, rval):
        operator = (lambda x, y: z3.BVSubNoUnderflow(x, y, False))
        operator = op.sub
        P4BinaryOp.__init__(self, lval, rval, operator)


class P4mul(P4BinaryOp):
    def __init__(self, lval, rval):
        operator = op.mul
        P4BinaryOp.__init__(self, lval, rval, operator)


class P4mod(P4BinaryOp):
    def __init__(self, lval, rval):
        operator = op.mod
        P4BinaryOp.__init__(self, lval, rval, operator)


class P4pow(P4BinaryOp):
    def __init__(self, lval, rval):
        operator = op.pow
        P4BinaryOp.__init__(self, lval, rval, operator)


class P4band(P4BinaryOp):
    def __init__(self, lval, rval):
        operator = op.and_
        P4BinaryOp.__init__(self, lval, rval, operator)


class P4bor(P4BinaryOp):
    def __init__(self, lval, rval):
        operator = op.or_
        P4BinaryOp.__init__(self, lval, rval, operator)


class P4land(P4BinaryOp):
    def __init__(self, lval, rval):
        operator = z3.And
        P4BinaryOp.__init__(self, lval, rval, operator)

    def eval(self, p4_state):
        lval_expr = resolve_expr(p4_state, self.lval)
        if lval_expr == False:
            return z3.BoolVal(False)
        rval_expr = resolve_expr(p4_state, self.rval)
        # if we compare to enums, do not use them for operations
        # for some reason, overloading equality does not work here...
        # instead reference a named bitvector of size 8
        # this represents a choice
        lval_expr, rval_expr = align_bitvecs(
            lval_expr, rval_expr, p4_state)
        return self.operator(lval_expr, rval_expr)


class P4lor(P4BinaryOp):
    def __init__(self, lval, rval):
        operator = z3.Or
        P4BinaryOp.__init__(self, lval, rval, operator)

    def eval(self, p4_state):

        lval_expr = resolve_expr(p4_state, self.lval)
        if lval_expr == True:
            return z3.BoolVal(True)
        rval_expr = resolve_expr(p4_state, self.rval)
        # if we compare to enums, do not use them for operations
        # for some reason, overloading equality does not work here...
        # instead reference a named bitvector of size 8
        # this represents a choice
        lval_expr, rval_expr = align_bitvecs(
            lval_expr, rval_expr, p4_state)
        return self.operator(lval_expr, rval_expr)


class P4xor(P4BinaryOp):
    def __init__(self, lval, rval):
        operator = op.xor
        P4BinaryOp.__init__(self, lval, rval, operator)


class P4div(P4BinaryOp):
    def __init__(self, lval, rval):
        operator = z3.UDiv
        P4BinaryOp.__init__(self, lval, rval, operator)


class P4lshift(P4BinaryOp):
    def __init__(self, lval, rval):
        operator = op.lshift
        P4BinaryOp.__init__(self, lval, rval, operator)


class P4rshift(P4BinaryOp):
    def __init__(self, lval, rval):
        operator = op.rshift
        P4BinaryOp.__init__(self, lval, rval, operator)


class P4lt(P4BinaryOp):
    def __init__(self, lval, rval):
        operator = op.lt
        P4BinaryOp.__init__(self, lval, rval, operator)


class P4le(P4BinaryOp):
    def __init__(self, lval, rval):
        operator = op.le
        P4BinaryOp.__init__(self, lval, rval, operator)


class P4eq(P4BinaryOp):
    def __init__(self, lval, rval):
        operator = op.eq
        P4BinaryOp.__init__(self, lval, rval, operator)


class P4ne(P4BinaryOp):
    def __init__(self, lval, rval):
        def operator(x, y): return z3.Not(op.eq(x, y))
        P4BinaryOp.__init__(self, lval, rval, operator)


class P4ge(P4BinaryOp):
    def __init__(self, lval, rval):
        operator = op.ge
        P4BinaryOp.__init__(self, lval, rval, operator)


class P4gt(P4BinaryOp):
    def __init__(self, lval, rval):
        operator = op.gt
        P4BinaryOp.__init__(self, lval, rval, operator)


class P4Mask(P4BinaryOp):
    # TODO: Check if this mask operator is right
    def __init__(self, lval, rval):
        operator = op.and_
        P4BinaryOp.__init__(self, lval, rval, operator)


class P4Slice(P4Expression):
    def __init__(self, val, slice_l, slice_r):
        self.val = val
        self.slice_l = slice_l
        self.slice_r = slice_r

    def eval(self, p4_state):
        val_expr = resolve_expr(p4_state, self.val)
        if isinstance(val_expr, int):
            val_expr = z3.BitVecVal(val_expr, 64)
        return z3.Extract(self.slice_l, self.slice_r, val_expr)


class P4Concat(P4Expression):
    def __init__(self, lval, rval):
        self.lval = lval
        self.rval = rval

    def eval(self, p4_state):
        lval_expr = resolve_expr(p4_state, self.lval)
        rval_expr = resolve_expr(p4_state, self.rval)
        return z3.Concat(lval_expr, rval_expr)


class P4Index(P4Expression):
    def __new__(cls, lval, index):
        cls.lval = lval
        cls.index = index
        return f"{lval}.{index}"

    def eval(cls, p4_state):
        lval_expr = resolve_expr(p4_state, cls.lval)
        index = resolve_expr(p4_state, cls.index)
        expr = lval_expr.resolve_reference(str(index))
        return expr


class P4Path(P4Expression):
    def __init__(self, val):
        self.val = val

    def eval(self, p4_state):
        val_expr = resolve_expr(p4_state, self.val)
        return val_expr


class P4Member(P4Expression):

    def __new__(cls, lval, member):
        cls.lval = lval
        cls.member = member
        return f"{lval}.{member}"

    def eval(cls, p4_state):
        if isinstance(cls.lval, P4Expression):
            lval = cls.lval.eval(p4_state)
        else:
            lval = cls.lval
        if isinstance(cls.member, P4Expression):
            member = cls.member.eval(p4_state)
        else:
            member = cls.member
        return f"{lval}.{member}"


class P4Cast(P4Expression):
    # TODO: need to take a closer look on how to do this correctly...
    # If we cast do we add/remove the least or most significant bits?
    def __init__(self, val, to_size: z3.BitVecSortRef):
        self.val = val
        self.to_size = to_size

    def eval(self, p4_state):
        expr = resolve_expr(p4_state, self.val)
        return z3_cast(expr, self.to_size)


class P4Mux(P4Expression):
    def __init__(self, cond, then_val, else_val):
        self.cond = cond
        self.then_val = then_val
        self.else_val = else_val

    def eval(self, p4_state):
        cond = resolve_expr(p4_state, self.cond)
        then_val = resolve_expr(p4_state, self.then_val)
        else_val = resolve_expr(p4_state, self.else_val)
        then_val = check_p4_type(then_val)
        else_val = check_p4_type(else_val)
        return z3.If(cond, then_val, else_val)


class P4Initializer(P4Expression):
    def __init__(self, val, instance):
        self.val = val
        self.instance = instance

    def eval(self, p4_state):
        instance = resolve_expr(p4_state, self.instance)
        val = resolve_expr(p4_state, self.val)
        if isinstance(val, P4ComplexType):
            return val
        if isinstance(instance, P4ComplexType):
            if isinstance(val, dict):
                for name, val in val.items():
                    val_expr = resolve_expr(p4_state, val)
                    instance.set_or_add_var(name, val_expr)
            elif isinstance(val, list):
                instance.set_list(val)
            else:
                raise RuntimeError(
                    f"P4StructInitializer members {val} not supported!")
            return instance
        else:
            return val


class MethodCallExpr(P4Expression):

    def __init__(self, p4_method, *args, **kwargs):
        self.p4_method = p4_method
        self.args = args
        self.kwargs = kwargs

    def eval(self, p4_state):
        p4_method = self.p4_method
        if isinstance(p4_method, str):
            # if we get a reference just try to find the method in the state
            p4_method = p4_state.resolve_reference(p4_method)
        if callable(p4_method):
            return p4_method(p4_state, *self.args, **self.kwargs)
        raise TypeError(f"Unsupported method type {type(p4_method)}!")


class P4Context(P4Z3Class):

    def __init__(self, var_buffer, p4_state=None):
        self.var_buffer = var_buffer
        self.p4_state = p4_state

    def eval(self, p4_context):
        if self.p4_state:
            log.debug("Restoring original p4 state %s to %s ",
                      p4_context, self.p4_state)
            expr_chain = p4_context.expr_chain
            p4_state = self.p4_state
            p4_state.expr_chain = expr_chain
        else:
            p4_state = p4_context
        var_buffer = self.var_buffer
        # restore any variables that may have been overridden
        # TODO: Fix to handle state correctly
        for param_name, param in var_buffer.items():
            is_ref = param[0]
            param_val = param[1]
            if param_val is None:
                # value has not existed previously, marked for deletion
                log.debug("Deleting %s", param_name)
                p4_state.del_var(param_name)
            elif (is_ref == "inout" or is_ref == "out"):
                val = p4_context.resolve_reference(param_name)
                log.debug("Copy-out: %s to %s", val, param_val)
                if isinstance(param_val, P4Slice):
                    # again the hope is that the slice value is a string...
                    slice_l = param_val.slice_l
                    slice_r = param_val.slice_r
                    param_val = param_val.val
                    arg_val = resolve_expr(p4_state, param_val)
                    val = slice_assign(arg_val, val, slice_l, slice_r)
                p4_state.set_or_add_var(param_val, val)
            elif is_ref == "in":
                val = p4_state.resolve_reference(param_name)
                log.debug("info %s with %s", param_name, val)
                p4_state.set_or_add_var(param_name, val)
        return step(p4_state)


class P4Callable(P4Z3Class):
    def __init__(self):
        self.block = BlockStatement()
        self.params = OrderedDict()
        self.call_counter = 0

    def add_parameter(self, param=None):
        if param:
            is_ref = param[0]
            param_name = param[1]
            param_type = param[2]
            self.params[param_name] = (is_ref, param_type)

    def get_parameters(self):
        return self.params

    def merge_parameters(self, *args, **kwargs):
        merged_params = {}
        args_len = len(args)
        for idx, param_name in enumerate(self.params.keys()):
            is_ref = self.params[param_name][0]
            if idx < args_len:
                merged_params[param_name] = (is_ref, args[idx])
        for arg_name, arg_val in kwargs.items():
            is_ref = self.params[arg_name][0]
            merged_params[arg_name] = (is_ref, arg_val)
        return merged_params

    def save_variables(self, p4_state, merged_params):
        var_buffer = {}
        # save all the variables that may be overridden
        for param_name, param in merged_params.items():
            var_buffer[param_name] = param
        return var_buffer

    def __call__(self, p4_state=None, *args, **kwargs):
        # for controls and externs, the state is not required
        # controls can only be executed with apply statements
        if p4_state:
            return self.eval(p4_state, *args, **kwargs)
        return self

    def eval_callable(self, p4_state, merged_params, var_buffer):
        pass

    def eval(self, p4_state=None, *args, **kwargs):
        self.call_counter += 1
        merged_params = self.merge_parameters(*args, **kwargs)
        var_buffer = self.save_variables(p4_state, merged_params)
        return self.eval_callable(p4_state, merged_params, var_buffer)


class P4Action(P4Callable):

    def __init__(self):
        super(P4Action, self).__init__()

    def add_stmt(self, block):
        if not isinstance(block, BlockStatement):
            raise RuntimeError(f"Expected a block, got {block}!")
        self.block = block

    def eval_callable(self, p4_state, merged_params, var_buffer):
        # override the symbolic entries if we have concrete
        # arguments from the table
        for param_name, param in merged_params.items():
            is_ref = param[0]
            arg = param[1]
            param_sort = self.params[param_name][1]
            log.debug("P4Action: Setting %s as %s ", param_name, arg)
            if is_ref == "out":
                # outs are left-values so the arg must be a string
                arg_name = arg
                arg_const = z3.Const(f"{param_name}", param_sort)
                # except slices can also be lvalues...
                if isinstance(arg, P4Slice):
                    # again the hope is that the slice value is a string...
                    arg_name = arg.val
                    arg_val = resolve_expr(p4_state, arg_name)
                    slice_l = arg.slice_l
                    slice_r = arg.slice_r
                    arg_const = slice_assign(
                        arg_val, arg_const, slice_l, slice_r)
                p4_state.set_or_add_var(arg_name, arg_const)
            # Sometimes expressions are passed, resolve those first
            arg = resolve_expr(p4_state, arg)
            log.debug("Copy-in: %s to %s", arg, param_name)
            p4_state.set_or_add_var(param_name, arg)
        # execute the action expression with the new environment
        p4_state.insert_exprs([self.block, P4Context(var_buffer)])
        # reset to the previous execution chain
        return step(p4_state)


class P4Function(P4Callable):

    def __init__(self, return_type):
        self.return_type = return_type
        super(P4Function, self).__init__()

    def add_stmt(self, block):
        if not isinstance(block, BlockStatement):
            raise RuntimeError(f"Expected a block, got {block}!")
        self.block = block

    def eval_callable(self, p4_state, merged_params, var_buffer):

        # override the symbolic entries if we have concrete
        # arguments from the table
        for param_name, param in merged_params.items():
            is_ref = param[0]
            arg = param[1]
            param_sort = self.params[param_name][1]
            log.debug("P4Action: Setting %s as %s ", param_name, arg)
            if is_ref == "out":
                # outs are left-values so the arg must be a string
                arg_name = arg
                arg_const = z3.Const(f"{param_name}", param_sort)
                # except slices can also be lvalues...
                if isinstance(arg, P4Slice):
                    # again the hope is that the slice value is a string...
                    arg_name = arg.val
                    arg_val = resolve_expr(p4_state, arg_name)
                    slice_l = arg.slice_l
                    slice_r = arg.slice_r
                    arg_const = slice_assign(
                        arg_val, arg_const, slice_l, slice_r)
                p4_state.set_or_add_var(arg_name, arg_const)
            # Sometimes expressions are passed, resolve those first
            arg = resolve_expr(p4_state, arg)
            log.debug("Copy-in: %s to %s", arg, param_name)
            p4_state.set_or_add_var(param_name, arg)
        # reset to the previous execution chain
        if self.return_type is not None:
            return self.block.eval(p4_state)
        # execute the action expression with the new environment
        p4_state.insert_exprs([self.block, P4Context(var_buffer)])
        return step(p4_state)


class P4Control(P4Callable):

    def __init__(self):
        super(P4Control, self).__init__()
        self.locals = []
        self.state_initializer = None

    def declare_local(self, local_name, local_var):
        decl = P4Declaration(local_name, local_var)
        self.block.add(decl)

    def add_instance(self, z3_reg, name, params):
        for param in params:
            self.add_parameter(param)
        self.state_initializer = (z3_reg, name)

    def add_stmt(self, stmt):
        self.block.add(stmt)

    def apply(self, p4_state, *args, **kwargs):
        return self.eval(p4_state, *args, **kwargs)

    def eval(self, p4_state=None, *args, **kwargs):
        self.call_counter += 1
        # initialize the local context of the function for execution
        z3_reg = self.state_initializer[0]
        name = self.state_initializer[1]
        p4_state_context = z3_reg.init_p4_state(name, self.params)
        p4_state_cpy = copy(p4_state)
        if not p4_state:
            # There is no state yet, so use the context of the function
            p4_state = p4_state_context

        merged_params = self.merge_parameters(*args, **kwargs)
        var_buffer = self.save_variables(p4_state, merged_params)

        # override the symbolic entries if we have concrete
        # arguments from the table
        for param_name, param in merged_params.items():
            is_ref = param[0]
            arg = param[1]
            param_sort = self.params[param_name][1]
            # FIXME: Hack to avoid awkward instantiations
            if isinstance(arg, z3.SortRef):
                continue
            if is_ref == "out":
                # outs are left-values so the arg must be a string
                arg_name = arg
                arg_const = z3.Const(f"{param_name}", param_sort)
                # except slices can also be lvalues...
                if isinstance(arg, P4Slice):
                    # again the hope is that the slice value is a string...
                    arg_name = arg.val
                    arg_val = resolve_expr(p4_state, arg_name)
                    slice_l = arg.slice_l
                    slice_r = arg.slice_r
                    arg_const = slice_assign(
                        arg_val, arg_const, slice_l, slice_r)
                p4_state.set_or_add_var(arg_name, arg_const)
            # Sometimes expressions are passed, resolve those first
            arg = resolve_expr(p4_state, arg)
            # var_buffer[param_name] = p4_state.get_var(param_name)
            log.debug("P4Control: Setting %s as %s %s",
                      param_name, arg, type(arg))
            p4_state_context.set_or_add_var(param_name, arg)

        # execute the action expression with the new environment
        p4_state_context.expr_chain = p4_state.copy_expr_chain()
        p4_state_context.insert_exprs(
            [self.block, P4Context(var_buffer, p4_state_cpy)])
        return step(p4_state_context)


class P4Extern(P4Callable):
    # TODO: This is quite brittle, requires concrete examination
    def __init__(self, name, z3_reg, return_type=None):
        super(P4Extern, self).__init__()
        self.name = name
        self.z3_reg = z3_reg
        # P4Methods, which are also black-box functions, can have return types
        self.return_type = return_type

    def add_method(self, name, method):
        setattr(self, name, method)

    def eval(self, p4_state=None, *args, **kwargs):
        self.call_counter += 1
        if not p4_state:
            # There is no state yet, so use the context of the function
            p4_state = self.z3_reg.init_p4_state(self.name, self.params)
            p4_state = p4_state

        merged_params = self.merge_parameters(*args, **kwargs)
        # externs can return values, we need to generate a new constant
        # we generate the name based on the input arguments
        var_name = ""
        for param_name, param in merged_params.items():
            is_ref = param[0]
            arg = param[1]
            log.debug("Extern: Setting %s as %s ", param_name, arg)
            # Because we do not know what the extern is doing
            # we initiate a new z3 const and just overwrite all reference types
            # we can assume that arg is a lvalue here (i.e., a string)
            arg_expr = resolve_expr(p4_state, arg)
            if isinstance(arg_expr, P4ComplexType):
                arg_expr = arg_expr.name

            if is_ref == "out" or is_ref == "inout":
                # Externs often have generic types until they are called
                # This call resolves the argument and gets its z3 type
                arg_type = get_type(p4_state, arg)
                name = f"{self.name}_{param_name}"
                extern_mod = z3.Const(name, arg_type)
                instance = self.z3_reg.instance(name, arg_type)
                # In the case that the instance is a complex type make sure
                # to propagate the variable through all its members
                if isinstance(instance, P4ComplexType):
                    instance.propagate_type(extern_mod)
                # Finally, assign a new value to the pass-by-reference argument
                p4_state.set_or_add_var(arg, instance)
            # input arguments influence the output behavior
            # add the input value to the return constant
            var_name += str(arg_expr)
        if self.return_type is not None:
            # If we return something, instantiate the type and return it
            # we merge the name
            # FIXME: We do not consider call order
            # and assume that externs are stateless
            return_instance = self.z3_reg.instance(
                f"{self.name}_{var_name}", self.return_type)
            return return_instance
        return p4_state.get_z3_repr()


class P4Parser(P4Control):
    pass


class P4Declaration(P4Statement):
    # the difference between a P4Declaration and a P4Assignment is that
    # we resolve the variable in the P4Assignment
    # in the declaration we assign variables as is.
    # they are resolved at runtime by other classes
    def __init__(self, lval, rval):
        self.lval = lval
        self.rval = rval

    def eval(self, p4_state):
        p4_state.set_or_add_var(self.lval, self.rval)
        return step(p4_state)


class SliceAssignment(P4Statement):
    def __init__(self, lval, rval, slice_l, slice_r):
        self.lval = lval
        self.rval = rval
        self.slice_l = slice_l
        self.slice_r = slice_r

    def find_nested_slice(self, lval, slice_l, slice_r):
        # gradually reduce the scope until we have calculated the right slice
        # also retrieve the string lvalue in the mean time
        if isinstance(lval, P4Slice):
            lval, outer_slice_l, outer_slice_r = self.find_nested_slice(
                lval.val, lval.slice_l, lval.slice_r)
            slice_l = outer_slice_r + slice_l
            slice_r = outer_slice_r + slice_r
        return lval, slice_l, slice_r

    def eval(self, p4_state):
        log.debug("Assigning %s to %s ", self.rval, self.lval)
        lval = self.lval
        rval = self.rval
        slice_l = self.slice_l
        slice_r = self.slice_r
        lval, slice_l, slice_r = self.find_nested_slice(lval, slice_l, slice_r)

        lval_expr = resolve_expr(p4_state, lval)
        rval_expr = resolve_expr(p4_state, rval)
        rval_expr = slice_assign(lval_expr, rval_expr, slice_l, slice_r)
        p4_state.set_or_add_var(lval, rval_expr)
        return step(p4_state)


class AssignmentStatement(P4Statement):
    # AssignmentStatements are essentially just a wrapper class for the
    # set_or_add_var ḿethod of the p4 state.
    # All the important logic is handled there.

    def __init__(self, lval, rval):
        self.lval = lval
        self.rval = rval

    def eval(self, p4_state):
        log.debug("Assigning %s to %s ", self.rval, self.lval)
        rval_expr = resolve_expr(p4_state, self.rval)
        p4_state.set_or_add_var(self.lval, rval_expr)
        return step(p4_state)


class MethodCallStmt(P4Statement):

    def __init__(self, method_expr):
        self.method_expr = method_expr

    def eval(self, p4_state):
        expr = self.method_expr.eval(p4_state)
        if p4_state.expr_chain:
            return step(p4_state)
        else:
            return expr


class BlockStatement(P4Statement):

    def __init__(self):
        self.exprs = []

    def preprend(self, expr):
        self.exprs.insert(0, expr)

    def add(self, expr):
        self.exprs.append(expr)

    def eval(self, p4_state):
        p4_state.insert_exprs(self.exprs)
        return step(p4_state)


class IfStatement(P4Statement):

    def __init__(self):
        self.cond = None
        self.then_block = None
        self.else_block = None

    def add_condition(self, cond):
        self.cond = cond

    def add_then_stmt(self, stmt):
        self.then_block = stmt

    def add_else_stmt(self, stmt):
        self.else_block = stmt

    def eval(self, p4_state):
        if self.cond is None:
            raise RuntimeError("Missing condition!")
        cond = resolve_expr(p4_state, self.cond)
        # conditional branching requires a copy of the state for each branch
        # in some sense this copy acts as a phi function
        then_p4_state = deepcopy(p4_state)
        then_expr = self.then_block.eval(then_p4_state)
        if self.else_block:
            else_expr = self.else_block.eval(p4_state)
            return z3.If(cond, then_expr, else_expr)
        else:
            return z3_implies(p4_state, cond, then_expr)


class SwitchHit(P4Expression):
    def __init__(self, table, cases, default_case):
        self.table = table
        self.default_case = default_case
        self.cases = cases

    def eval_cases(self, p4_state, cases):
        expr = self.default_case.eval(p4_state)
        for case in reversed(cases.values()):
            p4_state = deepcopy(p4_state)
            case_expr = case["case_block"].eval(p4_state)
            expr = z3.If(case["match"], case_expr, expr)
        return expr

    def eval_switch_matches(self, table):
        for case_name, case in self.cases.items():
            match_var = case["match_var"]
            action = table.actions[case_name][0]
            self.cases[case_name]["match"] = (match_var == action)

    def eval(self, p4_state):
        self.eval_switch_matches(self.table)
        switch_hit = self.eval_cases(p4_state, self.cases)
        return switch_hit


class SwitchStatement(P4Statement):
    # TODO: Fix fall through for switch statement
    def __init__(self, table_str):
        self.table_str = table_str
        self.default_case = BlockStatement()
        self.cases = OrderedDict()

    def add_case(self, action_str):
        # skip default statements, they are handled separately
        if action_str == "default":
            return
        case = {}
        case["match_var"] = z3.Int(f"{self.table_str}_action")
        case["case_block"] = BlockStatement()
        self.cases[action_str] = case

    def add_stmt_to_case(self, action_str, case_stmt):
        if action_str == "default":
            self.default_case.add(case_stmt)
        else:
            case_block = self.cases[action_str]["case_block"]
            case_block.add(case_stmt)

    def eval(self, p4_state):
        table = p4_state.resolve_reference(self.table_str)
        # instantiate the hit expression
        switch_hit = SwitchHit(table, self.cases, self.default_case)
        p4_state.insert_exprs([table, switch_hit])
        return step(p4_state)


class P4Noop(P4Statement):

    def eval(self, p4_state):
        return step(p4_state)


class P4Exit(P4Statement):

    def eval(self, p4_state):
        # Exit the chain early
        p4_state.clear_expr_chain()
        return step(p4_state)


class P4Return(P4Statement):
    def __init__(self, expr=None):
        self.expr = expr

    def eval(self, p4_state):
        if self.expr is None:
            return p4_state.get_z3_repr()
        else:
            expr = resolve_expr(p4_state, self.expr)
            return expr


class P4Table(P4Z3Class):

    def __init__(self, name):
        self.name = name
        self.keys = []
        self.const_entries = []
        self.actions = OrderedDict()
        self.default_action = None
        self.tbl_action = z3.Int(f"{self.name}_action")

    def add_action(self, action_expr):
        action_name, action_args = resolve_action(action_expr)
        index = len(self.actions) + 1
        self.actions[action_name] = (index, action_name, action_args)

    def add_default(self, action_expr):
        action_name, action_args = resolve_action(action_expr)
        self.default_action = (0, action_name, action_args)

    def add_match(self, table_key):
        self.keys.append(table_key)

    def add_const_entry(self, const_keys, action_expr):

        if len(self.keys) != len(const_keys):
            raise RuntimeError("Constant keys must match table keys!")
        action_name, action_args = resolve_action(action_expr)
        self.const_entries.append((const_keys, (action_name, action_args)))

    def apply(self, p4_state):
        return self.eval(p4_state)

    def __call__(self, p4_state):
        # tables can only be executed with apply statements
        return self

    def eval_keys(self, p4_state):
        key_pairs = []
        if not self.keys:
            # there is nothing to match with...
            return z3.BoolVal(False)
        for index, key in enumerate(self.keys):
            key_eval = resolve_expr(p4_state, key)
            key_sort = get_type(p4_state, key_eval)
            key_match = z3.Const(f"{self.name}_key_{index}", key_sort)
            key_pairs.append(key_eval == key_match)
        return z3.And(key_pairs)

    def eval_action(self, p4_state, action_tuple):
        p4_action = action_tuple[0]
        p4_action_args = action_tuple[1]
        p4_action = p4_state.resolve_reference(p4_action)
        if not isinstance(p4_action, P4Action):
            raise TypeError(f"Expected a P4Action got {type(p4_action)}!")
        action_args = []
        p4_action_args_len = len(p4_action_args) - 1
        for idx, (arg_name, param) in enumerate(p4_action.params.items()):
            if idx > p4_action_args_len:
                arg_type = param[1]
                if isinstance(arg_type, z3.SortRef):
                    action_args.append(
                        z3.Const(f"{self.name}{arg_name}", arg_type))
                else:
                    action_args.append(arg_type)
            else:
                action_args.append(p4_action_args[idx])
        return p4_action(p4_state, *action_args)

    def eval_default(self, p4_state):
        if self.default_action is None:
            # In case there is no default action, the first action is default
            self.default_action = (0, "NoAction", ())
        _, action_name, p4_action_args = self.default_action
        log.debug("Evaluating default action...")
        return self.eval_action(p4_state,
                                (action_name, p4_action_args))

    def eval_table(self, p4_state):
        actions = self.actions
        const_entries = self.const_entries
        # first evaluate the default entry
        # state forks here
        expr = self.eval_default(deepcopy(p4_state))
        # then wrap constant entries around it
        for const_keys, action in reversed(const_entries):
            action_name = action[0]
            p4_action_args = action[1]
            matches = []
            # match the constant keys with the normal table keys
            # this generates the match expression for a specific constant entry
            for index, key in enumerate(self.keys):
                key_eval = resolve_expr(p4_state, key)
                const_key = const_keys[index]
                # default implies don't care, do not add
                # TODO: Verify that this assumption is right...
                if str(const_key) == "default":
                    continue
                c_key_eval = resolve_expr(
                    p4_state, const_keys[index])
                matches.append(key_eval == c_key_eval)
            action_match = z3.And(*matches)
            action_tuple = (action_name, p4_action_args)
            log.debug("Evaluating constant action %s...", action_name)
            action_expr = self.eval_action(deepcopy(p4_state), action_tuple)
            expr = z3.If(action_match, action_expr, expr)
        # then wrap dynamic table entries around the constant entries
        for action in reversed(actions.values()):

            p4_action_id = action[0]
            action_name = action[1]
            p4_action_args = action[2]
            action_match = (self.tbl_action == z3.IntVal(p4_action_id))
            action_tuple = (action_name, p4_action_args)
            log.debug("Evaluating action %s...", action_name)
            # state forks here
            action_expr = self.eval_action(deepcopy(p4_state), action_tuple)
            expr = z3.If(action_match, action_expr, expr)
        # finally return a nested set of if expressions
        return expr

    def eval(self, p4_state):
        # This is a table match where we look up the provided key
        # If we match select the associated action,
        # else use the default action
        # TODO: Check the exact semantics how default actions can be called
        # Right now, they can be called in either the table match or miss
        tbl_match = self.eval_keys(p4_state)
        table_expr = self.eval_table(p4_state)
        def_expr = self.eval_default(p4_state)
        return z3.If(tbl_match, table_expr, def_expr)
