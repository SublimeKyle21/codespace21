
/*GNU GPL v3

adjusts lod:=[0,1] per deltatime
not actually a PID
this differential-only approach is somehow more robust
idk maybe i just suck at PID tuning
*/

sat=(_)=>max(0,min(1,_))//saturate

var _lod= 0//previous frame
var _lod_lim= 1//maximum lod without lag
function lod(dt){
	let SHRINK= .1
	let GROW  = .1

	let target= 1/60;
	target*= 1.05;//todo replace this with proper vsync tolerance
	let actual= dt;
	let err= actual - target;//positive err means laggy; negative is within target

	let lod= _lod;
	let cap= _lod_lim;

	let shr= dt*SHRINK;
	let grw= dt*GROW;
	
	//prevent jitter
	let tolerance= 2*max(shr,grw);//must be larger than delta, or will never fall within range
	
	lod+= (err>tolerance)? -shr:grw;
	
	if(err>tolerance)//remember the maximum lod when fps<target
		cap*= 1.-shr;//very aggressive, todo

	cap= sat(cap);
	lod= sat(lod);
	lod= min(lod,cap);

	_lod= lod
	_lod_lim= cap;
	
	return _lod
}
