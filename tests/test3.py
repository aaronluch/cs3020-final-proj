# Test 3: three-field class to single-expression volume
class Box:
    depth: int
    height: int
    width: int

def volume(b: Box) -> int:
    return b.depth * b.height * b.width

b = Box(2, 3, 4)
print(volume(b)) # expect 24