let N_MAX = 4e6
let sh;
let img;
let attribs;
function preload() {
	sh = loadShader('vert.glsl', 'frag.glsl');

	attribs = {
		poss: new Float32Array(N_MAX * 6).map((e, i) => random(2,-1)),
		vels: new Float32Array(N_MAX * 20),
		cols: new Uint8Array(N_MAX*5).map((e,i)=>random()*(i/5)*i),
	}

	//disable right click
	document.addEventListener('contextmenu', event => event.preventDefault());
}

var gl
p5.RendererGL.prototype._initContext = function() { // hack thx to github.com/diwi/p5.EasyCam/blob/master/examples/ReactionDiffusion_Webgl2/ReactionDiffusion_Webgl2.js#L563
	this.drawingContext = this.canvas.getContext('webgl2', this._pInst._glAttributes); //dont forget attribs or thumbnail breaks
	if (this.drawingContext === null)
		alert('couldnt webgl2');
	gl = this.drawingContext;
};


let canv, W, H, ping, pong

function setup() {
	W = windowWidth;
	H = windowHeight;
	canv = createCanvas(W, H, WEBGL);
	gl.viewport(0, 0, W, H);
	canv._viewport = gl.getParameter(gl.VIEWPORT);

	pixelDensity(1);

	function buf() {

		let vao = gl.createVertexArray();
		gl.bindVertexArray(vao);


		let vbo_p = gl.createBuffer();
		gl.bindBuffer(gl.ARRAY_BUFFER, vbo_p);
		gl.bufferData(gl.ARRAY_BUFFER, attribs.poss, gl.DYNAMIC_DRAW);
		gl.enableVertexAttribArray(0);
		gl.vertexAttribPointer(0, 2, gl.FLOAT, false, 0, 0);

		let vbo_v = gl.createBuffer();
		gl.bindBuffer(gl.ARRAY_BUFFER, vbo_v);
		gl.bufferData(gl.ARRAY_BUFFER, attribs.vels, gl.DYNAMIC_DRAW);
		gl.enableVertexAttribArray(1);
		gl.vertexAttribPointer(1, 2, gl.FLOAT, false, 0, 0);

		/*
		let vbo_c = gl.createBuffer();
		gl.bindBuffer(gl.ARRAY_BUFFER, vbo_c);
		gl.bufferData(gl.ARRAY_BUFFER, attribs.cols, gl.DYNAMIC_DRAW);
		gl.enableVertexAttribArray(2);
		gl.vertexAttribPointer(2,3,gl.UNSIGNED_BYTE,true,0,0);
		*/


		let xfb = gl.createTransformFeedback();
		gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, xfb);
		gl.bindBufferBase(gl.TRANSFORM_FEEDBACK_BUFFER, 0, vbo_p);
		gl.bindBufferBase(gl.TRANSFORM_FEEDBACK_BUFFER, 1, vbo_v);


		gl.bindVertexArray(null);
		gl.bindBuffer(gl.ARRAY_BUFFER, null);
		gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, null);

		this.vao = vao;
		this.xfb = xfb;
	}
	ping = new buf();
	pong = new buf();


	//inject before the link stage
	//javascript.jpeg angels cry yet god laughs
	let hax = gl.linkProgram;
	Object.defineProperty(gl, 'linkProgram', {
		get: (function() {
			gl.transformFeedbackVaryings((() => sh._glProgram)(), ['v_p', 'v_v'], gl.SEPARATE_ATTRIBS);
			gl.linkProgram = hax; //run once
			return hax;
		})
	});
	shader(sh);

	//force shader compilation or something like that
	//this is necessary, even without the xform varyings, required before the draw loop
	rect(0, 0, 0, 0);;


	let err = gl.getError();
	if (err)
		print(err);
}
pingpong = () => {
	[ping, pong] = [pong, ping];
}


function draw() {
	n = lod(deltaTime / 1000) * N_MAX;

	gl.clearColor(.05, .05, .05, 1); //canvas has alpha. fbo0 is externally blended
	gl.clear(gl.COLOR_BUFFER_BIT);;

	//gl.enable(gl.GL_FRAMEBUFFER_SRGB)
	gl.disable(gl.DEPTH_TEST);
	gl.disable(gl.CULL_FACE);
	gl.enable(gl.BLEND);
	gl.blendFunc(gl.SRC_ALPHA, gl.ONE_MINUS_SRC_ALPHA);
	//gl.enable(gl.PROGRAM_POINT_SIZE) always on in webgl

	shader(sh);
	sh.setUniform('time', millis());
	//for the first few frames create initial clicks automatically
	if (frameCount < 500) {
		sh.setUniform('moose', [(random(0, width) / W * 2 - 1.) * W / H, (1. - random(0, height) / H) * 2 - 1.]);
		sh.setUniform('butts', [
			true,
			false, 
			false,
			0,
		]);
		sh.setUniform('asp', H / W);

	} else {
		sh.setUniform('moose', [(mouseX / W * 2 - 1.) * W / H, (1. - mouseY / H) * 2 - 1.]);
		sh.setUniform('butts', [
			mouseIsPressed && mouseButton == LEFT,
			mouseIsPressed && mouseButton == CENTER, //nobody calls it CENTER?? its called MIDDLE reeeeee
			mouseIsPressed && mouseButton == RIGHT,
			0,
		]);
		sh.setUniform('asp', H / W);
	}

	gl.bindVertexArray(ping.vao);
	gl.bindTransformFeedback(gl.TRANSFORM_FEEDBACK, pong.xfb);
	gl.beginTransformFeedback(gl.POINTS);
	gl.drawArrays(gl.POINTS, 0, n);
	gl.endTransformFeedback();
	gl.bindVertexArray(null);

	pingpong();

	//print(gl.getError())
}
