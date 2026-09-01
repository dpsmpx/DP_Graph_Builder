import matplotlib.pyplot as plt
import numpy as np
import math
from collections import deque

class ExpressionParser:
    def __init__(self):
        self.variables = {
            'Pi': math.pi,
            'E': math.e,
            'x': 0
        }
        self.functions = {
            'S': math.sin,
            'C': math.cos,
            'T': math.tan,
            'K': lambda x: 1/math.tan(x) if math.tan(x) != 0 else float('nan'),
            'С': math.asin,
            'К': math.acos,
            'Т': math.atan,
            'А': lambda x: math.atan(1/x) if x != 0 else float('nan')
        }
        self.operators = {
            '+': (1, lambda a, b: a + b),
            '-': (1, lambda a, b: a - b),
            '*': (2, lambda a, b: a * b),
            '/': (2, lambda a, b: a / b if b != 0 else float('nan')),
            '^': (3, lambda a, b: a ** b),
            '@': (3, lambda a, b: b ** (1/a)),
            'L': (3, lambda a, b: math.log(b, a) if a > 0 and a != 1 and b > 0 else float('nan')),
            '?': (0, lambda a, b: a if a > b else b)
        }
        self.unary_ops = {
            '!': lambda a: math.factorial(int(a)) if a >= 0 and a.is_integer() else float('nan'),
            '#': lambda a: abs(a)
        }

    def tokenize(self, expression):
        tokens = []
        buffer = ''
        i = 0

        while i < len(expression):
            char = expression[i]
            
            if char.isspace():
                if buffer:
                    tokens.append(buffer)
                    buffer = ''
                i += 1
                continue
                
            if char in '+-*/^@L?=!#' or char in self.functions:
                if buffer:
                    tokens.append(buffer)
                    buffer = ''
                tokens.append(char)
                i += 1
                continue
                
            if char.isalpha() or char == '.' or (char == '-' and not buffer and (not tokens or tokens[-1] in self.operators)):
                buffer += char
                i += 1
                continue
                
            if char.isdigit() or (char == '-' and buffer == '' and (i == 0 or expression[i-1] in self.operators or expression[i-1].isspace())):
                buffer += char
                i += 1
                continue
                
            raise ValueError(f"Недопустимый символ: {char}")
        
        if buffer:
            tokens.append(buffer)
            
        return tokens

    def parse_expression(self, tokens, x_value):
        self.variables['x'] = x_value
        output = deque()
        operators = []
        assign_var = None
        
        for token in tokens:
            if token == '=':
                if not output:
                    raise ValueError("Недопустимое присваивание")
                assign_var = output.pop()
                if assign_var not in 'abcdefghijklmnopqrstuvwxyz':
                    raise ValueError("Недопустимое имя переменной")
                continue
                
            if token.replace('.', '').replace('-', '').isdigit():
                output.append(float(token))
            elif token in self.variables:
                output.append(self.variables[token])
            elif token in 'abcdefghijklmnopqrstuvwxyz':
                output.append(self.variables.get(token, 0.0))
            elif token in self.functions:
                operators.append(('func', token))
            elif token in self.unary_ops:
                operators.append(('unary', token))
            elif token in self.operators:
                while operators and operators[-1][0] != '(' and self.operators[operators[-1][1]][0] >= self.operators[token][0]:
                    self.process_operator(operators, output)
                operators.append(('op', token))
            else:
                raise ValueError(f"Недопустимый токен: {token}")
                
        while operators:
            self.process_operator(operators, output)
            
        result = output.pop()
        
        if assign_var:
            self.variables[assign_var] = result
            
        return result

    def process_operator(self, operators, output):
        op_type, op_val = operators.pop()
        
        if op_type == 'unary':
            a = output.pop()
            output.append(self.unary_ops[op_val](a))
        elif op_type == 'func':
            a = output.pop()
            output.append(self.functions[op_val](a))
        elif op_type == 'op':
            b = output.pop()
            a = output.pop()
            output.append(self.operators[op_val][1](a, b))

    def evaluate(self, expression, x_value):
        tokens = self.tokenize(expression)
        return self.parse_expression(tokens, x_value)

class Plotter:
    def __init__(self):
        self.parser = ExpressionParser()
        self.x_center = 0
        self.y_center = 0
        self.scale = 5
        self.expression = "x/x^2"
        
        self.fig, self.ax = plt.subplots()
        self.fig.canvas.mpl_connect('key_press_event', self.on_key_press)
        self.plot()
        
    def plot(self):
        self.ax.clear()
        x_vals = np.linspace(self.x_center - self.scale, 
                             self.x_center + self.scale, 
                             1000)
        y_vals = []
        
        for x in x_vals:
            try:
                y = self.parser.evaluate(self.expression, x)
                y_vals.append(y)
            except:
                y_vals.append(float('nan'))
                
        self.ax.plot(x_vals, y_vals, 'b-')
        self.ax.set_title(f"y = {self.expression}")
        self.ax.grid(True)
        self.ax.set_xlim(self.x_center - self.scale, self.x_center + self.scale)
        self.ax.set_ylim(self.y_center - self.scale, self.y_center + self.scale)
        plt.draw()
    
    def on_key_press(self, event):
        if event.key == 'up':
            self.y_center += self.scale * 0.1
        elif event.key == 'down':
            self.y_center -= self.scale * 0.1
        elif event.key == 'left':
            self.x_center -= self.scale * 0.1
        elif event.key == 'right':
            self.x_center += self.scale * 0.1
        elif event.key == '+':
            self.scale *= 0.8
        elif event.key == '-':
            self.scale *= 1.25
        elif event.key == 'escape':
            new_expr = input("Введите новое выражение: ")
            if new_expr.strip():
                self.expression = new_expr
                self.parser.variables = {
                    'Pi': math.pi,
                    'E': math.e,
                    'x': 0
                }
        
        self.plot()

if __name__ == "__main__":
    plotter = Plotter()
    plt.show()