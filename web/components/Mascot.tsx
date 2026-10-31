"use client";

import { useEffect, useRef } from "react";
import * as THREE from "three";
import { RoomEnvironment } from "three/examples/jsm/environments/RoomEnvironment.js";

/** 3D-фигуры интерфейса. */

const GREEN = "#17c23a";
const MINT = "#6fdcbd";
const INK = "#14352c";
const BLACK = "#050706";

let grain: THREE.CanvasTexture | null = null;

/** Мелкая зернистость матового стекла. */
function grainTexture(): THREE.CanvasTexture {
  if (grain) return grain;
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 256;
  const context = canvas.getContext("2d")!;
  const image = context.createImageData(256, 256);
  for (let i = 0; i < image.data.length; i += 4) {
    const value = 110 + Math.random() * 100;
    image.data.set([value, value, value, 255], i);
  }
  context.putImageData(image, 0, 0);
  grain = new THREE.CanvasTexture(canvas);
  grain.wrapS = grain.wrapT = THREE.RepeatWrapping;
  grain.repeat.set(3, 3);
  return grain;
}

export const solid = (color: string) =>
  new THREE.MeshPhysicalMaterial({ color, roughness: 0.3, clearcoat: 0.7, clearcoatRoughness: 0.25 });

const metal = (color: string) => new THREE.MeshPhysicalMaterial({ color, metalness: 0.85, roughness: 0.3 });

function jelly(color: string, opacity: number) {
  return new THREE.MeshPhysicalMaterial({
    color, transparent: opacity < 1, opacity, roughness: 0.46, clearcoat: 1, clearcoatRoughness: 0.32,
    emissive: new THREE.Color(color), emissiveIntensity: 0.16, bumpMap: grainTexture(), bumpScale: 0.5,
  });
}

function extrude(shape: THREE.Shape, depth: number, bevel: number): THREE.BufferGeometry {
  const geometry = new THREE.ExtrudeGeometry(shape, {
    depth, bevelEnabled: true, bevelSize: bevel, bevelThickness: bevel, bevelSegments: 8, curveSegments: 48,
  });
  geometry.center();
  return geometry;
}

function roundedRect(width: number, height: number, radius: number): THREE.Shape {
  const x = -width / 2;
  const y = -height / 2;
  const shape = new THREE.Shape();
  shape.moveTo(x + radius, y);
  shape.lineTo(x + width - radius, y);
  shape.quadraticCurveTo(x + width, y, x + width, y + radius);
  shape.lineTo(x + width, y + height - radius);
  shape.quadraticCurveTo(x + width, y + height, x + width - radius, y + height);
  shape.lineTo(x + radius, y + height);
  shape.quadraticCurveTo(x, y + height, x, y + height - radius);
  shape.lineTo(x, y + radius);
  shape.quadraticCurveTo(x, y, x + radius, y);
  return shape;
}

function sparkShape(): THREE.Shape {
  const shape = new THREE.Shape();
  shape.moveTo(0, 1);
  shape.quadraticCurveTo(0.12, 0.12, 1, 0);
  shape.quadraticCurveTo(0.12, -0.12, 0, -1);
  shape.quadraticCurveTo(-0.12, -0.12, -1, 0);
  shape.quadraticCurveTo(-0.12, 0.12, 0, 1);
  return shape;
}

function halfRing(): THREE.Shape {
  const end = Math.PI / 2 - 0.09;
  const shape = new THREE.Shape();
  shape.absarc(0, 0, 1.3, -end, end, false);
  shape.absarc(0, 0, 0.76, end, -end, true);
  shape.closePath();
  return shape;
}

export function makeEmblem() {
  const group = new THREE.Group();
  const halfGeometry = extrude(halfRing(), 0.3, 0.06);
  const right = new THREE.Mesh(halfGeometry, jelly(GREEN, 1));
  right.position.x = 0.68;
  const left = new THREE.Mesh(halfGeometry, jelly(MINT, 0.84));
  left.rotation.z = Math.PI;
  left.position.x = -0.68;
  const star = new THREE.Mesh(extrude(sparkShape(), 0.1, 0.05), jelly("#35d98a", 1));
  star.scale.setScalar(0.54);
  group.add(left, right, star);
  return { group, left, right, star };
}

function disc(color: string, radius: number): THREE.Mesh {
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, 0.2, 96), solid(color));
  mesh.rotation.x = Math.PI / 2;
  return mesh;
}

function lens(radius: number): THREE.Mesh {
  const canvas = document.createElement("canvas");
  canvas.width = canvas.height = 256;
  const context = canvas.getContext("2d")!;
  const gradient = context.createRadialGradient(170, 90, 10, 128, 128, 190);
  gradient.addColorStop(0, "#a6f7c0");
  gradient.addColorStop(0.5, "#3fc99a");
  gradient.addColorStop(1, "#1a8f86");
  context.fillStyle = gradient;
  context.fillRect(0, 0, 256, 256);
  const face = new THREE.MeshPhysicalMaterial({ map: new THREE.CanvasTexture(canvas), transparent: true, opacity: 0.7, roughness: 0.12, clearcoat: 1 });
  const edge = new THREE.MeshPhysicalMaterial({ color: "#cfe9dd", roughness: 0.2, metalness: 0.4 });
  const mesh = new THREE.Mesh(new THREE.CylinderGeometry(radius, radius, 0.035, 96), [edge, face, face]);
  mesh.rotation.x = Math.PI / 2;
  return mesh;
}

function asterisk(): THREE.Group {
  const group = new THREE.Group();
  const material = metal("#21d05a");
  for (let i = 0; i < 3; i += 1) {
    const arm = new THREE.Mesh(extrude(roundedRect(0.3, 1.8, 0.06), 0.24, 0.03), material);
    arm.rotation.z = (i * Math.PI) / 3;
    group.add(arm);
  }
  return group;
}

export function makePill(text: string, fill = INK, ink = "#ffffff"): THREE.Group {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 192;
  const context = canvas.getContext("2d")!;
  context.font = "800 92px system-ui, -apple-system, sans-serif";
  const textWidth = context.measureText(text).width;
  context.fillStyle = ink;
  context.textAlign = "center";
  context.textBaseline = "middle";
  const scale = Math.min(1, 460 / textWidth);
  context.setTransform(scale, 0, 0, scale, 256, 100);
  context.fillText(text, 0, 0);
  const width = Math.max(1.5, (Math.min(textWidth, 460) / 512) * 2.5 + 0.7);

  const map = new THREE.CanvasTexture(canvas);
  map.colorSpace = THREE.SRGBColorSpace; // иначе цвет надписи выходит бледнее заданного

  const group = new THREE.Group();
  group.add(new THREE.Mesh(extrude(roundedRect(width, 0.74, 0.37), 0.14, 0.13), solid(fill)));
  const label = new THREE.Mesh(
    new THREE.PlaneGeometry(2.5, 0.94),
    new THREE.MeshBasicMaterial({ map, transparent: true }),
  );
  label.position.z = 0.21;
  group.add(label);
  return group;
}

export function makeCursor(): THREE.Group {
  const group = new THREE.Group();
  const matte = new THREE.MeshStandardMaterial({ color: BLACK, roughness: 0.6 }); // без лака: блик красил стрелку в зелёный
  const cone = new THREE.Mesh(new THREE.ConeGeometry(0.46, 0.86, 64), matte);
  const stem = new THREE.Mesh(new THREE.CylinderGeometry(0.15, 0.15, 0.42, 32), matte);
  stem.position.y = -0.6;
  group.add(cone, stem);
  return group;
}

export function makeDecor() {
  return { disc, lens, asterisk };
}

export function lighting(scene: THREE.Scene, renderer: THREE.WebGLRenderer) {
  const generator = new THREE.PMREMGenerator(renderer);
  scene.environment = generator.fromScene(new RoomEnvironment(), 0.04).texture;
  scene.environmentIntensity = 0.5;
  generator.dispose();
  const key = new THREE.DirectionalLight("#ffffff", 1.6);
  key.position.set(2, 4, 5);
  scene.add(key);
  const rim = new THREE.DirectionalLight("#7dffc0", 1.4);
  rim.position.set(-4, -1, 2);
  scene.add(rim);
}

export function makeRenderer(canvas?: HTMLCanvasElement): THREE.WebGLRenderer {
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true, preserveDrawingBuffer: !canvas });
  renderer.toneMapping = THREE.NoToneMapping;
  renderer.setClearColor(0x000000, 0);
  return renderer;
}

export type Mood = "idle" | "thinking" | "happy";
export type Variant = "emblem" | "hero" | "pills";

type Floating = { object: THREE.Object3D; x: number; y: number; speed: number; spin: number };

function hero(scene: THREE.Scene): Floating[] {
  const { disc, lens, asterisk } = makeDecor();
  const place = (shape: THREE.Object3D, x: number, y: number, z: number, speed: number, spin: number, scale = 1): Floating => {
    // Обёртка нужна, чтобы покачивание не сбрасывало собственный поворот фигуры.
    const object = new THREE.Group();
    object.add(shape);
    object.scale.setScalar(scale);
    object.position.set(x, y, z);
    scene.add(object);
    return { object, x, y, speed, spin };
  };
  const star = asterisk();
  star.scale.setScalar(0.42);
  return [
    place(disc("#16b8c4", 0.95), -1.3, -1.45, -1.8, 0.5, 0.5),
    place(disc("#7be84a", 0.72), 1.3, 1.75, -1.4, 0.7, 0.55),
    place(lens(0.8), 1.25, -1.45, 0.9, 0.6, 0.45),
    place(star, -1.35, 1.95, 0.4, 0.8, 0.5),
    place(makePill("Бриф"), -1.5, -0.45, 1.2, 0.9, 0.12, 0.7),
    place(makePill("Креатив", "#d8f97a", "#14352c"), 1.45, 0.72, 1.0, 1.05, 0.12, 0.7),
  ];
}

function pills(scene: THREE.Scene): Floating[] {
  const place = (object: THREE.Object3D, x: number, y: number, z: number, angle: number): Floating => {
    object.position.set(x, y, z);
    object.rotation.z = angle;
    scene.add(object);
    return { object, x, y, speed: 0.9, spin: 0.1 };
  };
  const cursor = makeCursor();
  cursor.rotation.z = 0.7;
  return [
    place(makePill("Уже"), -0.1, 0.42, 0, -0.08),
    place(makePill("в эфире", "#d8f97a", "#2b6a4d"), 0.45, -0.5, 0.3, 0.1),
    place(cursor, -1.05, -0.5, 0.8, 0.7),
  ];
}

/** Живая эмблема ассистента: половины дышат, звезда вращается, всё тянется к курсору. */
export function Mascot({ mood = "idle", variant = "emblem", className }: { mood?: Mood; variant?: Variant; className?: string }) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const moodRef = useRef(mood);
  moodRef.current = mood;

  useEffect(() => {
    const element = canvas.current;
    if (!element) return;

    let renderer: THREE.WebGLRenderer;
    try {
      renderer = makeRenderer(element);
    } catch {
      return; // без WebGL интерфейс работает и без фигур
    }
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2));

    const scene = new THREE.Scene();
    lighting(scene, renderer);
    const camera = new THREE.PerspectiveCamera(30, 1, 0.1, 50);
    const distance = variant === "hero" ? 11 : variant === "pills" ? 7.4 : 6.6;
    camera.position.z = distance;

    const root = new THREE.Group();
    scene.add(root);
    const emblem = variant === "pills" ? null : makeEmblem();
    if (emblem) root.add(emblem.group);
    const floating = variant === "hero" ? hero(scene) : variant === "pills" ? pills(scene) : [];

    const pointer = { x: 0, y: 0 };
    const onMove = (event: PointerEvent) => {
      pointer.x = (event.clientX / window.innerWidth - 0.5) * 2;
      pointer.y = (event.clientY / window.innerHeight - 0.5) * 2;
    };
    window.addEventListener("pointermove", onMove);

    const resize = () => {
      const { width, height } = element.getBoundingClientRect();
      if (!width || !height) return;
      renderer.setSize(width, height, false);
      camera.aspect = width / height;
      // Запас и в узком, и в низком окне: фигуры не упираются в край.
      camera.position.z = distance * Math.max(1, 1 / camera.aspect, variant === "hero" ? camera.aspect * 0.9 : 1);
      camera.updateProjectionMatrix();
    };
    const observer = new ResizeObserver(resize);
    observer.observe(element);
    resize();

    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let frame = 0;
    const started = performance.now();
    const draw = () => {
      const time = still ? 0.6 : (performance.now() - started) / 1000;
      const current = moodRef.current;

      root.rotation.y += (pointer.x * 0.5 - root.rotation.y) * 0.06;
      root.rotation.x += (pointer.y * 0.34 - root.rotation.x) * 0.06;
      root.position.y = current === "happy" ? Math.abs(Math.sin(time * 5)) * 0.2 : Math.sin(time * 1.2) * 0.06;

      if (emblem) {
        const gap = current === "thinking" ? 0.16 + Math.sin(time * 6) * 0.1 : 0.04 + Math.sin(time * 1.4) * 0.03;
        emblem.right.position.x = 0.68 + gap;
        emblem.left.position.x = -0.68 - gap;
        emblem.group.rotation.z = current === "thinking" ? time * 1.4 : Math.sin(time * 0.5) * 0.05;
        emblem.star.rotation.z = time * (current === "thinking" ? 3 : 0.5);
        emblem.star.scale.setScalar(0.54 + Math.sin(time * 2) * 0.03 + (current === "happy" ? 0.08 : 0));
      }

      for (const { object, x, y, speed, spin } of floating) {
        object.position.x = x + pointer.x * 0.1 + Math.sin(time * speed * 0.6 + y) * 0.06;
        object.position.y = y - pointer.y * 0.1 + Math.sin(time * speed + x) * 0.1;
        object.rotation.x = Math.sin(time * speed * 0.7 + x) * spin;
        object.rotation.y = Math.sin(time * speed * 0.5 + y) * (spin + 0.12);
      }

      renderer.render(scene, camera);
      if (!still) frame = requestAnimationFrame(draw);
    };
    draw();

    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      window.removeEventListener("pointermove", onMove);
      renderer.dispose();
    };
  }, [variant]);

  return <canvas ref={canvas} className={className ?? "mascot"} aria-hidden />;
}
