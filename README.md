# CS 3020 - Dataclasses (Simple Object System)
### Group Members: Aaron Luciano, Walter Clay
## Overview

This compiler extension adds basic support for object-oriented dataclasses on top of the existing tuple and function backend. We track named fields at compile time, allow dot‑access and constructor syntax in the front end, and then lower all dataclass operations into plain tuple and subscript primitives before generating x86.

## Implementation Approach

1. **Type & Symbol Tracking**
   We utilize global maps and sets to track declarations and types:
   * `tuple_var_types: Dict[str, List[type]]` - types of tuples introduced by `Prim('tuple', …)` or lowered dataclass instances.
   * `dataclass_var_types: Dict[str, Dict[str, type]]` - for each class name, a mapping from field name to its declared type.
   * `function_names: Set[str]` - all user-defined and builtin function names to distinguish calls.
   * `function_params: Dict[str, List[str]]` - parameter names in declaration order for each function.
   * `function_return_types: Dict[str, type]` - declared return types for all functions.

2. **Parser & AST**
   * We extended the front‑end AST to include a `ClassDef(name, base, fields_list)` node.
   * Field declarations `name: Type` inside a class become entries in `dataclass_var_types[name]`.

3. **Type Checking (`typecheck` pass)**
   * **Class Binding:** On encountering a `ClassDef`, register the class in `dataclass_var_types`.
   * **Constructor Calls:** Treat calls to a class name like functions; match positional arguments to fields, return a  `DataclassType`.
   * **Field Access:** `FieldRef(obj, field)` checks `obj`’s type is a dataclass, looks up the field’s declared type.
   * **Parameter Handling:** In `FunctionDef`, parameters declared with a class type are first bound to `DataclassType` to allow field accesses in the body, then lowered to tuple types for next passes.

4. **Lowering Objects (`eliminate_objects` pass)**
   * Runs immediately after `typecheck`.
   * **Rewrite Constructors:** `Call(ClassName, args…)` → `Prim('tuple', args…)`.
   * **Rewrite FieldRefs:** `FieldRef(o, f)` → `Prim('subscript', [o, Constant(i)])` where `i` is the field’s index in the original class definition.

5. **Downstream Passes**
   * After `eliminate_objects`, the AST consists solely of tuples, subscripts, and standard calls/prims.
   * Existing passes (RCO, Explicate Control, Select Instructions, Register Allocation) are unchanged on the lowered code from previous compiler implementation.

## Planned but Unimplemented Features
* **Default Field Values:** Declaration of default initializers in classes. (i.e: def \_\_init\_\_)
* **Update values through dot access:** Updating field values through dot notation syntax (e.g., `rect.length = 4`).
* **Named-argument Constructors:** Keyword-based construction (`Rectangle(len=5, width=10)`).
* **Inheritance & Methods:** Inheritance and method definitions inside classes.

## Build & Test
1. Have Python 3.x installed.
2. Ensure you have all required dependencies used in `compiler.py`
3. Run `python compiler.py 'tests/testfile.py'` to compile and print x86 code and formatted output.
4. To use `run_tests.py` to execute the all test cases concurrently:
   - First; you must download our version `run_tests.py`--this is because we did not modify the interpreter to handle this new implementation. The `run_tests.py` from the course directories handles these test cases differently.
   - Then, execute:
   ```
   python run_tests.py      # ensure you are in the proper directory of `compiler.py`
   ```
