"use client";

import { useEffect, useRef } from "react";

// Главный визуал — сфера из тысяч шипов, у которой «дышит» поверхность.
// Это не гифка и не видео: анимация считается в реальном времени на GPU,
// поэтому весит килобайты, остаётся чёткой на любом экране и в любой
// плотности пикселей, и бесшовно зациклена. Для сервиса про приватность
// это ещё и принципиально — никаких внешних CDN и сторонних ассетов.
//
// Три обязательных запасных пути:
//   1. prefers-reduced-motion — рисуем один статичный кадр, без цикла.
//   2. нет WebGL / контекст не создался — показываем CSS-заглушку.
//   3. вкладка скрыта или герой ушёл за экран — цикл встаёт, батарея цела.

// Компактный симплекс-шум Эшимы (3D), инлайном в вершинный шейдер —
// им гнём поверхность сферы, чтобы бугры плавно перетекали со временем.
const SNOISE = /* glsl */ `
vec3 mod289(vec3 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 mod289(vec4 x){return x-floor(x*(1.0/289.0))*289.0;}
vec4 permute(vec4 x){return mod289(((x*34.0)+1.0)*x);}
vec4 taylorInvSqrt(vec4 r){return 1.79284291400159-0.85373472095314*r;}
float snoise(vec3 v){
  const vec2 C=vec2(1.0/6.0,1.0/3.0);const vec4 D=vec4(0.0,0.5,1.0,2.0);
  vec3 i=floor(v+dot(v,C.yyy));vec3 x0=v-i+dot(i,C.xxx);
  vec3 g=step(x0.yzx,x0.xyz);vec3 l=1.0-g;vec3 i1=min(g.xyz,l.zxy);vec3 i2=max(g.xyz,l.zxy);
  vec3 x1=x0-i1+C.xxx;vec3 x2=x0-i2+C.yyy;vec3 x3=x0-D.yyy;
  i=mod289(i);
  vec4 p=permute(permute(permute(i.z+vec4(0.0,i1.z,i2.z,1.0))+i.y+vec4(0.0,i1.y,i2.y,1.0))+i.x+vec4(0.0,i1.x,i2.x,1.0));
  float n_=0.142857142857;vec3 ns=n_*D.wyz-D.xzx;
  vec4 j=p-49.0*floor(p*ns.z*ns.z);
  vec4 x_=floor(j*ns.z);vec4 y_=floor(j-7.0*x_);
  vec4 x=x_*ns.x+ns.yyyy;vec4 y=y_*ns.x+ns.yyyy;vec4 h=1.0-abs(x)-abs(y);
  vec4 b0=vec4(x.xy,y.xy);vec4 b1=vec4(x.zw,y.zw);
  vec4 s0=floor(b0)*2.0+1.0;vec4 s1=floor(b1)*2.0+1.0;vec4 sh=-step(h,vec4(0.0));
  vec4 a0=b0.xzyw+s0.xzyw*sh.xxyy;vec4 a1=b1.xzyw+s1.xzyw*sh.zzww;
  vec3 p0=vec3(a0.xy,h.x);vec3 p1=vec3(a0.zw,h.y);vec3 p2=vec3(a1.xy,h.z);vec3 p3=vec3(a1.zw,h.w);
  vec4 norm=taylorInvSqrt(vec4(dot(p0,p0),dot(p1,p1),dot(p2,p2),dot(p3,p3)));
  p0*=norm.x;p1*=norm.y;p2*=norm.z;p3*=norm.w;
  vec4 m=max(0.6-vec4(dot(x0,x0),dot(x1,x1),dot(x2,x2),dot(x3,x3)),0.0);m=m*m;
  return 42.0*dot(m*m,vec4(dot(p0,x0),dot(p1,x1),dot(p2,x2),dot(p3,x3)));
}
`;

export function SphereHero() {
  const wrapRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLCanvasElement | null>(null);

  useEffect(() => {
    const wrap = wrapRef.current;
    const canvas = canvasRef.current;
    if (!wrap || !canvas) return;

    const reduce = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;
    const coarse = window.matchMedia("(pointer: coarse)").matches;

    let disposed = false;
    let dispose = () => {};

    (async () => {
      let THREE: typeof import("three");
      try {
        THREE = await import("three");
      } catch {
        wrap.dataset.fallback = "true";
        return;
      }
      if (disposed) return;

      let renderer: import("three").WebGLRenderer;
      try {
        renderer = new THREE.WebGLRenderer({
          canvas,
          antialias: true,
          alpha: true,
          powerPreference: "high-performance",
        });
      } catch {
        wrap.dataset.fallback = "true";
        return;
      }

      const width = () => wrap.clientWidth || 1;
      const height = () => wrap.clientHeight || 1;
      const dprCap = coarse ? 1.75 : 2;

      renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, dprCap));
      renderer.setSize(width(), height(), false);
      renderer.toneMapping = THREE.ACESFilmicToneMapping;
      renderer.toneMappingExposure = 1.05;

      const scene = new THREE.Scene();
      const camera = new THREE.PerspectiveCamera(
        30,
        width() / height(),
        0.1,
        100,
      );
      camera.position.set(0, 0, 7.2);

      // Группа вращается; свет висит в мире, поэтому верх сферы всегда
      // подсвечен — ровно как на референсе, где источник сверху.
      const group = new THREE.Group();
      scene.add(group);

      // Плотность шипов под размер экрана: на телефоне их меньше, чтобы
      // не жечь GPU, на десктопе — гуще для «бархатной» поверхности.
      const w = width();
      const count = w < 640 ? 4600 : w < 1024 ? 7500 : 11000;

      const R = 1.72; // радиус сферы
      const spikeH = 0.12; // длина шипа — короткий, чтобы читался бархат

      // Шип — короткий гранёный конус. Сдвигаем геометрию так, чтобы
      // основание было в y=0, а остриё смотрело в +Y: тогда инстанс
      // ставит основание точно на сферу, а кончик — наружу.
      const geometry = new THREE.ConeGeometry(0.026, spikeH, 5, 1);
      geometry.translate(0, spikeH / 2, 0);

      const material = new THREE.MeshStandardMaterial({
        color: new THREE.Color(0x20242b),
        roughness: 0.62,
        metalness: 0.34,
        flatShading: true,
      });

      // Деформацию поверхности и разброс по фазе прокидываем в шейдер.
      const uniforms = {
        uTime: { value: reduce ? 2.5 : 0 },
        uAmp: { value: 0.16 },
        uFreq: { value: 1.25 },
      };
      material.onBeforeCompile = (shader) => {
        shader.uniforms.uTime = uniforms.uTime;
        shader.uniforms.uAmp = uniforms.uAmp;
        shader.uniforms.uFreq = uniforms.uFreq;
        shader.vertexShader =
          `attribute vec3 aDir;\nuniform float uTime;\nuniform float uAmp;\nuniform float uFreq;\n${SNOISE}\n` +
          shader.vertexShader.replace(
            "#include <begin_vertex>",
            `#include <begin_vertex>
             float n1 = snoise(aDir * uFreq + vec3(0.0, 0.0, uTime * 0.45));
             float n2 = 0.35 * snoise(aDir * (uFreq * 2.3) + vec3(uTime * 0.28, 0.0, 0.0));
             float disp = (n1 + n2) * uAmp;
             transformed.y += disp;`,
          );
      };

      const mesh = new THREE.InstancedMesh(geometry, material, count);
      mesh.frustumCulled = false;

      const dirs = new Float32Array(count * 3);
      const dummy = new THREE.Object3D();
      const dir = new THREE.Vector3();
      const up = new THREE.Vector3(0, 1, 0);
      const golden = Math.PI * (3 - Math.sqrt(5)); // золотой угол

      for (let i = 0; i < count; i++) {
        // Сфера Фибоначчи: равномерное распределение точек без полюсных
        // сгущений, которые дала бы обычная сетка по широте/долготе.
        const y = 1 - (i / (count - 1)) * 2;
        const r = Math.sqrt(Math.max(0, 1 - y * y));
        const theta = golden * i;
        dir.set(Math.cos(theta) * r, y, Math.sin(theta) * r).normalize();

        dirs[i * 3] = dir.x;
        dirs[i * 3 + 1] = dir.y;
        dirs[i * 3 + 2] = dir.z;

        dummy.position.copy(dir).multiplyScalar(R);
        dummy.quaternion.setFromUnitVectors(up, dir);
        const s = 0.85 + Math.random() * 0.32; // лёгкий разнобой длин
        dummy.scale.set(0.95, s, 0.95);
        dummy.updateMatrix();
        mesh.setMatrixAt(i, dummy.matrix);
      }
      mesh.instanceMatrix.needsUpdate = true;
      geometry.setAttribute("aDir", new THREE.InstancedBufferAttribute(dirs, 3));
      group.add(mesh);

      // Свет как на референсе: холодный ключевой сверху-слева, слабый
      // тёплый контровой снизу-справа для объёма, немного заполнения.
      const key = new THREE.DirectionalLight(0xdfeaff, 2.6);
      key.position.set(-3.2, 5.0, 4.0);
      const rim = new THREE.DirectionalLight(0x3b4c6b, 1.1);
      rim.position.set(4.0, -2.5, -3.5);
      const ambient = new THREE.AmbientLight(0x2a3550, 0.5);
      scene.add(key, rim, ambient);

      // Мышь чуть наклоняет сферу — «живой» отклик без резких движений.
      let targetX = 0;
      let targetY = 0;
      let curX = 0;
      let curY = 0;
      const onPointer = (e: PointerEvent) => {
        const rect = wrap.getBoundingClientRect();
        targetX = ((e.clientX - rect.left) / rect.width - 0.5) * 2;
        targetY = ((e.clientY - rect.top) / rect.height - 0.5) * 2;
      };
      if (!coarse && !reduce) {
        window.addEventListener("pointermove", onPointer, { passive: true });
      }

      const clock = new THREE.Clock();
      let spin = 0.35;
      let raf = 0;
      let visible = true;

      const renderFrame = () => {
        renderer.render(scene, camera);
      };

      const loop = () => {
        raf = requestAnimationFrame(loop);
        const dt = Math.min(clock.getDelta(), 0.05);
        uniforms.uTime.value += dt;
        spin += dt * 0.16;
        curX += (targetX - curX) * 0.045;
        curY += (targetY - curY) * 0.045;
        group.rotation.y = spin + curX * 0.35;
        group.rotation.x = -0.08 + curY * 0.22;
        renderFrame();
      };

      const start = () => {
        if (raf || reduce || !visible) return;
        clock.start();
        loop();
      };
      const stop = () => {
        if (!raf) return;
        cancelAnimationFrame(raf);
        raf = 0;
      };

      const resize = () => {
        renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, dprCap));
        renderer.setSize(width(), height(), false);
        camera.aspect = width() / height();
        camera.updateProjectionMatrix();
        renderFrame();
      };

      const ro = new ResizeObserver(resize);
      ro.observe(wrap);

      // Не крутим то, чего не видно.
      const io = new IntersectionObserver(
        (entries) => {
          visible = entries[0]?.isIntersecting ?? true;
          if (visible) start();
          else stop();
        },
        { threshold: 0.01 },
      );
      io.observe(wrap);

      const onVisibility = () => {
        if (document.hidden) stop();
        else start();
      };
      document.addEventListener("visibilitychange", onVisibility);

      // Первый кадр рисуем сразу — даже для reduced-motion сфера должна
      // появиться, просто без движения.
      group.rotation.set(-0.08, spin, 0);
      renderFrame();
      if (!reduce) start();

      dispose = () => {
        stop();
        ro.disconnect();
        io.disconnect();
        document.removeEventListener("visibilitychange", onVisibility);
        window.removeEventListener("pointermove", onPointer);
        geometry.dispose();
        material.dispose();
        renderer.dispose();
      };
    })();

    return () => {
      disposed = true;
      dispose();
    };
  }, []);

  return (
    <div ref={wrapRef} className="sphere-hero" aria-hidden="true">
      <canvas ref={canvasRef} className="sphere-canvas" />
      {/* Заглушка на случай, когда WebGL недоступен: та же форма,
          мягкое свечение, чтобы композиция не разваливалась. */}
      <div className="sphere-fallback" />
    </div>
  );
}
