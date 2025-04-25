class Rectangle:
    len: int
    width: int
    
def area(rectangle: Rectangle) -> int:
    return rectangle.len * rectangle.width

r = Rectangle(5, 10)
print(area(r))