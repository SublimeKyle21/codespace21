#version 300 es
precision mediump float;

flat in vec4 v_c;
out vec4 c;
void main() {
  c= v_c;
}
