// SPDX-License-Identifier: MIT
// Copyright (c) 2026 w0001111; upstream credits: AUTHORS.md and THIRD_PARTY.md.
import React, { useState } from 'react';
import { getView, saveView } from './viewState';

export function ReadingDetails({ viewKey, id, children, ...props }) {
  const [open, setOpen] = useState(() => !!getView(viewKey).disclosures?.[id]);
  return <details {...props} data-read-key={id} open={open} onToggle={e => {
    const value = e.currentTarget.open;
    setOpen(value);
    saveView(viewKey, { disclosures: { ...getView(viewKey).disclosures, [id]: value } });
  }}>{children}</details>;
}
