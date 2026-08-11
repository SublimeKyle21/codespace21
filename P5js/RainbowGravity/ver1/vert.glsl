#version 300 es
precision highp float;

const float FOV= 1.;//fieldofview

const float EV= .3;//exposure

const float BIGNESS= 1.;//particle size, pixels

const float BUMP= .005;//as in bumpmap

const float G= .00005; //gravitational coefficient




#define len length
#define lerp mix
#define norm normalize
#define nmaps(v) (v*2.-1.)

const float ETA= .123456e-8;

const vec3 LUMVEC= vec3(0.2126, 0.7152, 0.0722);
float lum(vec3 c){ return dot(c,LUMVEC); }


vec3 rgb2hsv(vec3 c){
    vec4 K = vec4(0.0, -1.0 / 3.0, 2.0 / 3.0, -1.0);
    vec4 p = mix(vec4(c.bg, K.wz), vec4(c.gb, K.xy), step(c.b, c.g));
    vec4 q = mix(vec4(p.xyw, c.r), vec4(c.r, p.yzx), step(p.x, c.r));

    float d = q.x - min(q.w, q.y);
    float e = 1.0e-10;
    return vec3(abs(q.z + (q.w - q.y) / (6.0 * d + e)), d / (q.x + e), q.x);
}
vec3 hsv2rgb(vec3 c){
    vec4 K = vec4(1.0, 2.0 / 3.0, 1.0 / 3.0, 3.0);
    vec3 p = abs(fract(c.xxx + K.xyz) * 6.0 - K.www);
    return c.z * mix(K.xxx, clamp(p - K.xxx, 0.0, 1.0), c.y);
}

vec3 nse_3_3(vec3 v){
	uvec3 x= uvec3(v*4321.);
	const uint k = 1103515245U;
	x = ((x>>8U)^x.yzx)*k;
	x = ((x>>8U)^x.yzx)*k;
	return vec3(x)*(2.0/float(0xffffffffU))-1.;
}

















uniform float time;
uniform vec2 moose;
uniform ivec4 butts;
uniform float asp;//apsect inverse


layout(location=0) in vec2 in_p;
layout(location=1) in vec2 in_v;
layout(location=2) in vec3 in_c;
out vec2 v_p;
out vec2 v_v;
flat out vec4 v_c;
void main(){

	//worldspace
	vec2 p= in_p;
	vec2 v= in_v;
	
	//kinesis
	vec2 o= vec2(moose); //attractor
	vec2 d= p-o; //delta position
	float l= max(.01,len(d+ETA));
	float g= 1./l; //gravity
	
	//buttons
	if(butts.x!=0)
		g= g*g/4.;
	if(butts.y!=0)
		p= lerp(p,in_c.xy,.1);
	if(butts.z!=0)
		g= 1./(g*g);

	//impulse
	vec2 j= norm(-d)*g*G;

	//integral, forward euler
	v+= j;
	p+= v;
	
	//boundary
	if(len(p)>2.5){
		p*= .025;
		v*= .25;
	}

	//xfeed out
	v_v= v;
	v_p= p;
	
	//projspace far:+z up:+y
	vec4 w= vec4(p,.5,FOV);
	w.x*= asp;
  gl_Position= w;//renegade lack of mvp
	
  gl_PointSize= BIGNESS;
	
	//vec4 col= vec4(in_c,1.);
	
	float h= len(v+ETA);
	h= sqrt(h*2.)*4.;
	vec3 c= hsv2rgb(vec3(h,1.,1.));
	//c/=LUMVEC;
	vec4 col= vec4( c, EV );
	v_c= col;
}
