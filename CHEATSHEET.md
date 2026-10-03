# Python Cheatsheet for JS / Java / C# / C++ devs

Python 3.12. Everything here runs as-is in `uv run python`.

---

## 1. The big mental shifts

- **Indentation is the syntax.** No braces and no semicolons. A block starts with `:` and is indented 4 spaces.
- **Dynamic typing plus optional type hints.** Hints aren't enforced at runtime. They're for your editor, for mypy/pyright, and for readers.
- **Everything is an object**, including ints, functions, classes, and modules.
- **No `private`/`public`.** By convention `_name` means internal and `__name` gets name-mangled. Nothing is truly hidden.
- **Variables are references**, as in JS and Java. Assigning never copies an object.
- **`None`** is the only null. There's no `undefined`.
- **snake_case** for variables, functions, and modules. **PascalCase** for classes. **UPPER_CASE** for constants (by convention only).

```python
if x > 0:
    print("positive")      # 4-space indent = block
elif x == 0:               # not "else if"
    pass                   # empty block needs `pass`
else:
    print("negative")
```

---

## 2. Operators: the ones that differ

| Python | JS / C-family | Notes |
|---|---|---|
| `and`, `or`, `not` | `&&`, `\|\|`, `!` | Return operands like JS: `name or "default"` |
| `a if cond else b` | `cond ? a : b` | Ternary, but in a different order |
| `x == y` | `x === y` (sort of) | Value equality. Calls `__eq__` |
| `x is y` | `===` on refs / `ReferenceEquals` | Identity. **Use for `None`**: `if x is None` |
| `7 / 2` → `3.5` | | `/` always returns a float |
| `7 // 2` → `3` | int division | Floor division (floors toward −∞: `-7 // 2 == -4`) |
| `2 ** 10` | `Math.pow` | Power |
| `x += 1` | `x++` | **There is no `++`/`--`** |
| `0 < x < 10` | `0 < x && x < 10` | Comparisons chain |
| `x in coll` | `.includes()` / `.contains()` | Works on list, str, dict (keys), set |
| `x not in coll` | | |
| `(n := len(a)) > 3` | | "Walrus": assigns inside an expression |

**Truthiness.** Falsy values are `None`, `False`, `0`, `0.0`, `""`, `[]`, `{}`, `set()`, `()`. Everything else is truthy.

```python
if not items:          # idiomatic "is empty" check
    ...
```

Ints are arbitrary-precision, so `2**200` just works and never overflows.

---

## 3. Strings

```python
s = 'single' + "double"          # same thing
multi = """triple quotes
span lines"""
name, n = "Ada", 3
f"Hi {name}, you have {n} msgs"  # f-string = template literal / $"..."
f"{n * 2}  {name!r}  {3.14159:.2f}  {n:>5}  {n=}"   # expressions, repr, format, debug

len(s)                           # not s.length
s.upper(), s.lower(), s.strip()  # strip = trim
s.split(","), ",".join(["a", "b"])   # join is called ON the separator
s.startswith("x"), s.replace("a", "b"), s.find("x")  # find returns -1 if missing
"ab" * 3                         # "ababab"
r"C:\raw\path"                   # raw string, no escape processing
```

Strings are **immutable**. Build big strings with a list and then `"".join(parts)`.

---

## 4. Collections

```python
# list: JS array / ArrayList / std::vector
nums = [3, 1, 2]
nums.append(4); nums.extend([5, 6]); nums.insert(0, 9)
nums.pop()          # remove last and return it
nums.pop(0)         # remove at index
nums.remove(3)      # remove first occurrence of VALUE
nums.sort(); sorted(nums, key=lambda x: -x, reverse=False)  # in-place vs new list
len(nums); nums[-1] # negative index = from the end

# tuple: immutable list, often a "lightweight record"
pt = (3, 4)
x, y = pt           # unpacking (destructuring)
single = (1,)       # trailing comma needed for a 1-tuple

# dict: JS object / Map / Dictionary / unordered_map (insertion-ordered)
user = {"name": "Ada", "age": 36}
user["name"]              # KeyError if missing
user.get("email")         # None if missing
user.get("email", "n/a")  # with a default
user["email"] = "a@b.c"
del user["age"]
"name" in user            # key check
for k, v in user.items(): ...
user.keys(), user.values()
merged = {**user, "age": 37}   # spread, like JS {...user}
merged = user | {"age": 37}    # same thing

# set: HashSet
tags = {"a", "b"}          # note: {} is an empty DICT; use set()
tags.add("c"); tags & {"a"}; tags | {"z"}; tags - {"a"}
```

### Slicing: `seq[start:stop:step]` (stop is exclusive)

```python
a = [0, 1, 2, 3, 4, 5]
a[1:4]    # [1, 2, 3]
a[:2]     # [0, 1]
a[-2:]    # [4, 5]
a[::-1]   # reversed copy
a[:]      # shallow copy
"hello"[1:3]  # "el", works on strings too
```

### Comprehensions (use these instead of map/filter)

```python
squares = [x * x for x in range(10)]                 # .map
evens   = [x for x in nums if x % 2 == 0]            # .filter
lookup  = {u["id"]: u for u in users}                # dict comprehension
unique  = {w.lower() for w in words}                 # set comprehension
total   = sum(x.price for x in cart)                 # generator expr, lazy, no []
```

Also useful: `any(...)`, `all(...)`, `min(..., key=...)`, `max(...)`, `sum(...)`.

---

## 5. Loops

```python
for item in items:                 # always "foreach"
    ...
for i in range(5): ...             # 0..4
for i in range(2, 10, 2): ...      # 2,4,6,8
for i, item in enumerate(items):   # index + value
    ...
for a, b in zip(xs, ys): ...       # iterate in parallel
for k, v in d.items(): ...

while cond:
    ...
    if done: break
    continue

for x in items:
    if x == target:
        break
else:                              # runs only if loop did NOT break
    print("not found")
```

There is no C-style `for (i=0; i<n; i++)`. Use `range`.

---

## 6. Functions

```python
def greet(name: str, greeting: str = "Hi") -> str:
    """Docstring: shows up in help() and your editor."""
    return f"{greeting}, {name}"

greet("Ada")
greet("Ada", greeting="Yo")    # keyword arguments, any order

def f(a, b, /, c, *, d):       # a,b positional-only; d keyword-only
    ...

def varargs(*args, **kwargs):  # args = tuple, kwargs = dict
    print(args, kwargs)
varargs(1, 2, x=3)             # (1, 2) {'x': 3}
varargs(*[1, 2], **{"x": 3})   # spreading into a call

def multi():
    return 1, "two"            # returns a tuple
n, s = multi()

square = lambda x: x * x       # single expression only; prefer def
```

**GOTCHA: mutable default arguments are evaluated ONCE.**

```python
def bad(item, bucket=[]):      # same list shared across all calls!
    bucket.append(item); return bucket

def good(item, bucket=None):
    if bucket is None:
        bucket = []
    bucket.append(item); return bucket
```

**Scope.** Functions can read outer variables. To *reassign* one, you need `global x` or `nonlocal x`. Blocks (`if`/`for`) do **not** create scope, so a loop variable still exists after the loop.

---

## 7. Classes

```python
class Animal:
    species_count = 0                     # class attribute (like static)

    def __init__(self, name: str):        # constructor. `self` is explicit
        self.name = name                  # fields are created by assignment
        self._secret = 42                 # "_" = please don't touch
        Animal.species_count += 1

    def speak(self) -> str:               # every method takes self first
        return f"{self.name} makes a sound"

    def __repr__(self) -> str:            # debug print (like toString)
        return f"Animal({self.name!r})"

    @property
    def shout_name(self) -> str:          # getter: a.shout_name (no parens)
        return self.name.upper()

    @staticmethod
    def helper(x): return x * 2

    @classmethod
    def from_dict(cls, d: dict) -> "Animal":   # alternative constructor
        return cls(d["name"])


class Dog(Animal):                        # inheritance
    def __init__(self, name: str, breed: str):
        super().__init__(name)
        self.breed = breed

    def speak(self) -> str:               # override (no keyword needed)
        return f"{self.name} barks"

d = Dog("Rex", "lab")                     # no `new`
isinstance(d, Animal)                     # instanceof
```

Dunder ("double underscore") methods are how operators work: `__eq__`, `__lt__`, `__hash__`, `__len__`, `__iter__`, `__getitem__`, `__call__`, `__enter__`/`__exit__`, `__str__`.

### Dataclasses: use them for data (like records in C# and Java)

```python
from dataclasses import dataclass, field

@dataclass
class Message:
    role: str
    content: str
    tokens: int = 0
    tags: list[str] = field(default_factory=list)   # mutable default, done right

m = Message("user", "hi")      # __init__, __repr__, __eq__ generated for you

@dataclass(frozen=True)        # immutable + hashable
class Point:
    x: float
    y: float
```

### Interfaces: `Protocol` (structural, like TS) or `ABC` (nominal, like Java)

```python
from typing import Protocol
from abc import ABC, abstractmethod

class Tool(Protocol):                 # any class with this shape matches
    name: str
    def run(self, args: dict) -> str: ...

class BaseTool(ABC):                  # must subclass; can't instantiate
    @abstractmethod
    def run(self, args: dict) -> str: ...
```

### Enums

```python
from enum import Enum, StrEnum
class Role(StrEnum):
    USER = "user"
    ASSISTANT = "assistant"
Role.USER == "user"   # True for StrEnum
```

---

## 8. Type hints

```python
x: int = 5
names: list[str] = []
scores: dict[str, float] = {}
pair: tuple[int, str] = (1, "a")
maybe: str | None = None               # nullable (Optional[str] in older code)
def f(cb: Callable[[int], str]) -> None: ...   # from collections.abc import Callable
from typing import Any, Literal, TypedDict
Mode = Literal["fast", "slow"]         # string-literal union like TS

class ToolCall(TypedDict):             # typed shape for a plain dict (JSON-ish)
    name: str
    input: dict[str, Any]

def first[T](xs: list[T]) -> T:        # generics (3.12 syntax)
    return xs[0]
```

Hints are **not checked at runtime**. For static checking, add a checker with `uv add --dev pyright` and then run `uv run pyright`. Use **pydantic** if you need runtime validation, for example of LLM JSON output.

---

## 9. Errors

```python
try:
    data = json.loads(raw)
except json.JSONDecodeError as e:          # catch specific first
    print(f"bad json: {e}")
except (KeyError, ValueError):
    ...
except Exception as e:                     # catch-all (avoid bare `except:`)
    raise RuntimeError("wrapped") from e   # chain the cause
else:
    print("ran only if no exception")
finally:
    cleanup()

raise ValueError("message")                # `raise`, not `throw`

class ToolError(Exception):                # custom exception
    pass
```

Python style is **EAFP** ("easier to ask forgiveness than permission"): try the operation and catch the error, rather than checking everything first.

---

## 10. Context managers (`with`) = `using` / try-with-resources / RAII

```python
from pathlib import Path

with open("notes.txt", encoding="utf-8") as f:   # auto-closed
    text = f.read()

p = Path("data") / "out.json"          # `/` joins paths
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text("hi", encoding="utf-8")
p.read_text(encoding="utf-8")
p.exists(), p.suffix, p.stem
for file in Path(".").glob("**/*.py"): ...
```

On Windows, **always pass `encoding="utf-8"`**. Otherwise you get the system codepage.

---

## 11. Modules and imports

```python
import json                         # whole module: json.loads(...)
import numpy as np                  # alias
from pathlib import Path            # specific names
from harness.core import echo       # your own package (folder with __init__.py)
from . import sibling               # relative import (inside a package only)
```

- A **module** is a `.py` file. A **package** is a folder of modules, usually with `__init__.py`.
- Importing runs the file top to bottom, **once**. After that it's cached.
- This is the standard "main" guard, so a file can be both imported and run:

```python
def main() -> None: ...

if __name__ == "__main__":
    main()
```

---

## 12. Generators and iterators (lazy sequences)

```python
def count_up(n):
    i = 0
    while i < n:
        yield i            # pauses here; resumes on next()
        i += 1

for x in count_up(3): print(x)
gen = (x * x for x in range(10**9))   # lazy, costs no memory until iterated
next(gen)
```

These are handy for **streaming** LLM tokens or events.

---

## 13. Decorators = functions wrapping functions

```python
import functools, time

def timed(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        t = time.perf_counter()
        result = fn(*args, **kwargs)
        print(f"{fn.__name__} took {time.perf_counter() - t:.3f}s")
        return result
    return wrapper

@timed                     # same as: slow = timed(slow)
def slow(): time.sleep(0.1)
```

Agent frameworks use these a lot, for example `@tool` to register a function as an LLM tool.

---

## 14. async / await (like JS, but you start the event loop yourself)

```python
import asyncio

async def fetch(i: int) -> str:
    await asyncio.sleep(0.1)          # never time.sleep() in async code
    return f"result {i}"

async def main():
    one = await fetch(1)
    many = await asyncio.gather(*(fetch(i) for i in range(5)))   # Promise.all
    async with asyncio.timeout(5):    # timeout block
        await fetch(99)

asyncio.run(main())                   # entry point. Calling fetch() alone does NOTHING
```

- Calling an `async def` returns a coroutine, which is roughly an unstarted Promise. It only runs when awaited or scheduled.
- Iterate an async stream with `async for chunk in stream:`.
- Run blocking code without freezing the loop: `await asyncio.to_thread(blocking_fn, arg)`.

---

## 15. Stdlib you'll use in an agent harness

```python
import json
json.dumps(obj, indent=2)     # obj -> str      (JSON.stringify)
json.loads(s)                 # str -> obj      (JSON.parse)

import os
os.environ.get("ANTHROPIC_API_KEY")   # env vars (after load_dotenv())

import subprocess             # run shell commands (a classic agent tool)
r = subprocess.run(["git", "status"], capture_output=True, text=True, timeout=30)
r.returncode, r.stdout, r.stderr

import logging
logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)
log.info("calling tool %s", name)     # lazy formatting

from datetime import datetime, timezone
datetime.now(timezone.utc).isoformat()

import uuid; str(uuid.uuid4())
import re; re.findall(r"\d+", "a1b22")          # ['1', '22']
from collections import defaultdict, Counter, deque
import argparse                                 # CLI args
```

---

## 16. Misc idioms

```python
a, b = b, a                           # swap
first, *rest = [1, 2, 3]              # rest = [2, 3]
print(*items, sep=", ")               # print with separator
print(x, end="")                      # no newline
input("prompt> ")                     # read a line from stdin
del x                                 # unbind a name / delete an item
isinstance(x, (int, float))           # type check
type(x).__name__
dir(obj); help(obj)                   # explore in the REPL
breakpoint()                          # drop into the debugger (pdb)

match event:                          # structural pattern matching (3.10+)
    case {"type": "text", "text": t}:
        print(t)
    case {"type": "tool_use", "name": name, "input": args}:
        run_tool(name, args)
    case Message(role="user"):        # match on class fields
        ...
    case _:                           # default
        pass
```

---

## 17. Gotcha list

| Gotcha | Fix |
|---|---|
| `def f(x=[])` default is shared | `x=None` then `if x is None: x = []` |
| `{}` is an empty dict, not a set | `set()` |
| `b = a` for a list doesn't copy | `a.copy()`, `list(a)`, `a[:]`, `copy.deepcopy(a)` |
| `[[0]*3]*3` gives 3 references to the same row | `[[0]*3 for _ in range(3)]` |
| `x == None` | `x is None` |
| Modifying a list while iterating over it | Iterate a copy, or build a new list |
| Lambdas in a loop capture the variable, not its value | `lambda i=i: i` |
| Tabs vs spaces mix | Always 4 spaces (ruff format handles it) |
| `0.1 + 0.2 != 0.3` | `math.isclose()` or `decimal.Decimal` |
| Forgot `self` in a method signature | Every instance method starts with `self` |
| Forgot to `await` / `asyncio.run` | A coroutine that's never awaited never runs (you get a warning) |
| File name shadows a stdlib module (`json.py`, `random.py`) | Don't name your files after stdlib modules |
| Windows file encoding | `encoding="utf-8"` everywhere |
