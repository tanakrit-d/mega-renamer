import React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva } from 'class-variance-authority';
import { clsx } from 'clsx';
import { twMerge } from 'tailwind-merge';
export const cn = (...inputs) => twMerge(clsx(inputs));
const variants = cva('button', {variants: {variant: {default: 'primary', outline: 'outline', ghost: 'ghost'}} , defaultVariants: {variant: 'default'}});
export const Button = React.forwardRef(({className, variant, asChild = false, ...props}, ref) => {
  const Component = asChild ? Slot : 'button';
  return <Component ref={ref} className={cn(variants({variant}), className)} {...props}/>;
});
Button.displayName = 'Button';
