  .globl main
add_pointstart:
  movq %rdi, %r8
  movq %rsi, %r8
  movq 8(%rdi), %rax
  addq 8(%rsi), %rax
  movq %rax, %r13
  movq 16(%rdi), %rax
  addq 16(%rsi), %rax
  movq %rax, %r14
  movq $24, %rdi
  callq allocate
  movq %rax, %r11
  movq $5, 0(%r11)
  movq %r13, 8(%r11)
  movq %r14, 16(%r11)
  movq %r11, -8(%r15)
  movq -8(%r15), %rax
  jmp add_pointconclusion
  movq $0, %rax
  jmp add_pointconclusion
add_point:
  pushq %rbp
  movq %rsp, %rbp
  pushq %rbx
  pushq %r12
  pushq %r13
  pushq %r14
  subq $0, %rsp
  movq $0, 0(%r15)
  addq $8, %r15
  jmp add_pointstart
add_pointconclusion:
  addq $0, %rsp
  subq $8, %r15
  popq %r14
  popq %r13
  popq %r12
  popq %rbx
  popq %rbp
  retq
mainstart:
  movq $24, %rdi
  callq allocate
  movq %rax, %r11
  movq $5, 0(%r11)
  movq $1, 8(%r11)
  movq $2, 16(%r11)
  movq %r11, -8(%r15)
  movq -8(%r15), %rax
  movq %rax, -16(%r15)
  movq $24, %rdi
  callq allocate
  movq %rax, %r11
  movq $5, 0(%r11)
  movq $3, 8(%r11)
  movq $4, 16(%r11)
  movq %r11, -24(%r15)
  movq -24(%r15), %rax
  movq %rax, -32(%r15)
  pushq %rdx
  pushq %rcx
  pushq %rsi
  pushq %rdi
  pushq %r8
  pushq %r9
  pushq %r10
  movq -16(%r15), %rdi
  movq -32(%r15), %rsi
  callq add_point
  popq %r10
  popq %r9
  popq %r8
  popq %rdi
  popq %rsi
  popq %rcx
  popq %rdx
  movq %rax, %r8
  movq %r8, %r8
  movq %r8, %rdi
  callq print_int
  movq $0, %rax
  jmp mainconclusion
main:
  pushq %rbp
  movq %rsp, %rbp
  pushq %rbx
  pushq %r12
  pushq %r13
  pushq %r14
  subq $0, %rsp
  movq $16384, %rdi
  movq $16, %rsi
  callq initialize
  movq rootstack_begin(%rip), %r15
  movq $0, 0(%r15)
  addq $8, %r15
  movq $0, 0(%r15)
  addq $8, %r15
  movq $0, 0(%r15)
  addq $8, %r15
  movq $0, 0(%r15)
  addq $8, %r15
  jmp mainstart
mainconclusion:
  addq $0, %rsp
  subq $32, %r15
  popq %r14
  popq %r13
  popq %r12
  popq %rbx
  popq %rbp
  retq

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
